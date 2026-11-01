"""The one place a backend is wired to core, for the CLI and for in-process consumers.

`main()` (`cli/main.py`) parses a command dataclass, opens a `Driver` for one command, runs it and
prints `envelope.to_wire`. A consumer such as
`examples/business_suite/schedule.py` opens one `Driver` for its whole run: it holds the device
lock throughout (A3-4) and pays process start and device facts once.

Wiring order, each step a Refusal on failure:
1. pick the device: `device.select_device(hub.connected(), -d, the ref's device)`;
2. merge policies: package default, the device profile from `<state root>/profiles/` and its
   policy files, then caller files (`rules.merge`). A profile or a policy file that does not
   parse is POLICY_INVALID before the device is locked or opened;
3. take the device lock `devices/<serial>/lock` (flock; DEVICE_BUSY after the wait budget);
4. open the backend, read `DeviceInfo`;
5. build `Context`.

Setup failures arrive as `PhoneError`, like every other failure a consumer sees.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import ExitStack, contextmanager
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from agent_phone.adapters.uiautomator2.adb import SubprocessAdb
from agent_phone.adapters.uiautomator2.phone import U2Hub
from agent_phone.cli.commands import INPUT_TIMEOUT_MS, DriverCommand, ScreenshotCommand
from agent_phone.cli.policy import load_policy, load_profiles, profile_for
from agent_phone.cli.request import TargetLike, effects, predicates, target_of
from agent_phone.cli.settings import Settings
from agent_phone.core.act.intent import Direction
from agent_phone.core.act.ledger import Ledger
from agent_phone.core.commands import (
    click,
    clipboard,
    find,
    get,
    is_,
    launch,
    open_url,
    press,
    rotate,
    screenshot,
    scroll,
    set_text,
    snapshot,
    stop,
    wait,
)
from agent_phone.core.commands.click import ClickCommand
from agent_phone.core.commands.clipboard import ClipboardGetCommand, ClipboardSetCommand
from agent_phone.core.commands.find import DEFAULT_LIMIT, FindCommand, Found
from agent_phone.core.commands.get import GetCommand, GetProperty
from agent_phone.core.commands.is_ import IsCommand, IsProperty
from agent_phone.core.commands.launch import LaunchCommand
from agent_phone.core.commands.open_url import OpenUrlCommand
from agent_phone.core.commands.press import PressCommand
from agent_phone.core.commands.rotate import RotateCommand
from agent_phone.core.commands.scroll import ScrollCommand
from agent_phone.core.commands.set_text import SetTextCommand
from agent_phone.core.commands.snapshot import SnapshotCommand
from agent_phone.core.commands.stop import StopCommand
from agent_phone.core.commands.wait import WaitCommand
from agent_phone.core.context import Context
from agent_phone.core.device import Package, Serial, select_device
from agent_phone.core.outcome import Acted, Outcome, Read, Refusal, Refused, Value
from agent_phone.core.phone import KeyName, Orientation, PhoneHub
from agent_phone.core.policy.rules import Effect
from agent_phone.core.query import Query
from agent_phone.core.refs.store import DeviceLock, SnapshotStore
from agent_phone.core.screen import WindowId
from agent_phone.core.snapshot.scope import SETTLE_TIMEOUT_MS, Scope
from agent_phone.core.snapshot.snapshot import RefToken, Snapshot
from agent_phone.core.snapshot.surface import Pick
from agent_phone.core.snapshot.view import Mode
from agent_phone.core.wait.clock import Clock, SystemClock
from agent_phone.core.wait.predicate import Predicate


def acted(outcome: Outcome) -> Acted:
    """The outcome of an input that went out and did what was asked, or PhoneError."""
    if isinstance(outcome, Acted) and outcome.error is None:
        return outcome
    raise PhoneError(outcome)


def device_lock(settings: Settings, serial: Serial, clock: Clock, command: str) -> DeviceLock:
    """The claim on one device for one command or one Driver session (A3-4). It creates the state
    root closed to other users, because snapshots under it hold what the screen showed."""
    settings.state_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    return SnapshotStore(settings.state_root).lock(serial, clock, settings.lock_wait_s, command)


class PhoneError(Exception):
    """Raised by `Driver` methods when the outcome is not ok. `outcome.disposition` says
    whether the consumer may try the same step again."""

    def __init__(self, outcome: Outcome, device: Serial | None = None) -> None:
        super().__init__(str(outcome))
        self.outcome = outcome
        self.device = device


class Driver:
    """The public API. Each method runs the same `core/commands/<name>.py` function the CLI
    runs, so a consumer cannot reach the device by a path the CLI does not have."""

    def __init__(self, ctx: Context, state_root: Path) -> None:
        self._ctx = ctx
        self._state_root = state_root

    @property
    def serial(self) -> Serial:
        return self._ctx.info.identity.serial

    def run(self, command: DriverCommand) -> Outcome:
        """The one dispatch over command dataclasses, for `main()` and for the typed methods."""
        ctx = self._ctx
        match command:
            case SnapshotCommand():
                return snapshot.run(ctx, command)
            case FindCommand():
                return find.run(ctx, command)
            case GetCommand():
                return get.run(ctx, command)
            case IsCommand():
                return is_.run(ctx, command)
            case WaitCommand():
                return wait.run(ctx, command)
            case ClickCommand():
                return click.run(ctx, command)
            case SetTextCommand():
                return set_text.run(ctx, command)
            case ScrollCommand():
                return scroll.run(ctx, command)
            case PressCommand():
                return press.run(ctx, command)
            case LaunchCommand():
                return launch.run(ctx, command)
            case StopCommand():
                return stop.run(ctx, command)
            case OpenUrlCommand():
                return open_url.run(ctx, command)
            case RotateCommand():
                return rotate.run(ctx, command)
            case ClipboardGetCommand() | ClipboardSetCommand():
                return clipboard.run(ctx, command)
            case ScreenshotCommand():
                return screenshot.run(ctx, command.path or self.screenshot_path())

    def screenshot_path(self) -> Path:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
        return self._state_root / "devices" / self.serial / "screenshots" / f"{stamp}.jpg"

    def snapshot(
        self,
        mode: Mode = Mode.COMPACT,
        settle: bool = False,
        root: RefToken | None = None,
        timeout_ms: int = SETTLE_TIMEOUT_MS,
        pick: Pick = Pick.ACTIVE,
        window: WindowId | None = None,
    ) -> Snapshot:
        outcome = self.run(SnapshotCommand(mode, settle, Scope(pick, window, root), timeout_ms))
        if isinstance(outcome, Read) and isinstance(outcome.payload, Snapshot):
            return outcome.payload
        raise PhoneError(outcome)

    def find(
        self,
        query: Query,
        *,
        limit: int = DEFAULT_LIMIT,
        pick: Pick = Pick.ACTIVE,
        window: WindowId | None = None,
        root: RefToken | None = None,
    ) -> Found:
        """Every match on the surface is counted and up to `limit` are listed, as lines of a new
        snapshot that owns their refs."""
        outcome = self.run(FindCommand(query, limit, False, Scope(pick, window, root)))
        if isinstance(outcome, Read) and isinstance(outcome.payload, Found):
            return outcome.payload
        raise PhoneError(outcome)

    def count(
        self,
        query: Query,
        *,
        pick: Pick = Pick.ACTIVE,
        window: WindowId | None = None,
        root: RefToken | None = None,
    ) -> int:
        outcome = self.run(FindCommand(query, DEFAULT_LIMIT, True, Scope(pick, window, root)))
        if isinstance(outcome, Read) and isinstance(outcome.payload, Found):
            return outcome.payload.count
        raise PhoneError(outcome)

    def get(
        self, ref: RefToken, property: GetProperty = GetProperty.TEXT
    ) -> str | tuple[int, ...] | tuple[str, ...] | None:
        """One property of the element, read live. None when it has no such property."""
        outcome = self.run(GetCommand(ref, property))
        if isinstance(outcome, Read) and isinstance(outcome.payload, Value):
            value = outcome.payload.value
            if value is None or isinstance(value, str | tuple):
                return value
        raise PhoneError(outcome)

    def is_(self, ref: RefToken, property: IsProperty = IsProperty.VISIBLE) -> bool:
        outcome = self.run(IsCommand(ref, property))
        if isinstance(outcome, Read) and isinstance(outcome.payload, Value):
            if isinstance(outcome.payload.value, bool):
                return outcome.payload.value
        raise PhoneError(outcome)

    def click(
        self,
        target: TargetLike,
        *,
        long: bool = False,
        commit: Effect | Sequence[Effect] = (),
        wait_for: Predicate | Sequence[Predicate] = (),
        timeout_ms: int = INPUT_TIMEOUT_MS,
    ) -> Acted:
        return acted(
            self.run(ClickCommand(target_of(target), long, effects(commit), predicates(wait_for), timeout_ms))
        )

    def set_text(
        self,
        target: TargetLike,
        text: str,
        *,
        wait_for: Predicate | Sequence[Predicate] = (),
        timeout_ms: int = INPUT_TIMEOUT_MS,
    ) -> Acted:
        return acted(self.run(SetTextCommand(target_of(target), text, predicates(wait_for), timeout_ms)))

    def scroll(
        self,
        direction: Direction,
        target: TargetLike | None = None,
        *,
        wait_for: Predicate | Sequence[Predicate] = (),
        timeout_ms: int = INPUT_TIMEOUT_MS,
    ) -> Acted:
        aimed = None if target is None else target_of(target)
        return acted(self.run(ScrollCommand(direction, aimed, predicates(wait_for), timeout_ms)))

    def press(
        self,
        key: KeyName,
        *,
        commit: Effect | Sequence[Effect] = (),
        wait_for: Predicate | Sequence[Predicate] = (),
        timeout_ms: int = INPUT_TIMEOUT_MS,
    ) -> Acted:
        return acted(self.run(PressCommand(key, effects(commit), predicates(wait_for), timeout_ms)))

    def launch(
        self,
        package: str,
        *,
        wait_for: Predicate | Sequence[Predicate] = (),
        timeout_ms: int = INPUT_TIMEOUT_MS,
    ) -> Acted:
        return acted(self.run(LaunchCommand(Package(package), predicates(wait_for), timeout_ms)))

    def stop(
        self,
        package: str,
        *,
        wait_for: Predicate | Sequence[Predicate] = (),
        timeout_ms: int = INPUT_TIMEOUT_MS,
    ) -> Acted:
        return acted(self.run(StopCommand(Package(package), predicates(wait_for), timeout_ms)))

    def open_uri(
        self,
        uri: str,
        package: str | None = None,
        *,
        commit: Effect | Sequence[Effect] = (),
        wait_for: Predicate | Sequence[Predicate] = (),
        timeout_ms: int = INPUT_TIMEOUT_MS,
    ) -> Acted:
        named = None if package is None else Package(package)
        return acted(self.run(OpenUrlCommand(uri, named, effects(commit), predicates(wait_for), timeout_ms)))

    def rotate(
        self,
        orientation: Orientation,
        *,
        wait_for: Predicate | Sequence[Predicate] = (),
        timeout_ms: int = INPUT_TIMEOUT_MS,
    ) -> Acted:
        return acted(self.run(RotateCommand(orientation, predicates(wait_for), timeout_ms)))

    def clipboard(self) -> str | None:
        outcome = self.run(ClipboardGetCommand())
        if isinstance(outcome, Read) and isinstance(outcome.payload, Value):
            value = outcome.payload.value
            if value is None or isinstance(value, str):
                return value
        raise PhoneError(outcome)

    def set_clipboard(self, text: str) -> Acted:
        return acted(self.run(ClipboardSetCommand(text)))

    def screenshot(self, path: Path | None = None) -> Path:
        outcome = self.run(ScreenshotCommand(path))
        if isinstance(outcome, Read) and isinstance(outcome.payload, Value):
            return Path(str(outcome.payload.value))
        raise PhoneError(outcome)


@contextmanager
def open_phone(
    serial: str | None = None,
    policies: Sequence[Path] = (),
    state_root: Path | None = None,
    *,
    hub: PhoneHub | None = None,
    settings: Settings | None = None,
    clock: Clock | None = None,
    command: str = "session",
    ref: RefToken | None = None,
    first_read: bool = False,
) -> Iterator[Driver]:
    """`with open_phone("0a1b2c3d4e5f6a7b", policies=[here / "policy.toml"]) as phone: ...`

    The device lock is held until the block ends, and the phone is closed then. `hub`, `settings`
    and `clock` are for tests and for consumers that bring their own; the defaults read the
    environment and use adb. A `ref` names its device through its snapshot, so no `serial` is
    needed when the ref is given. `first_read` is for a caller that reads once, straight after
    it opens, as the CLI does (`PhoneHub.open`).
    """
    try:
        settings = settings or Settings.from_environment()
    except Refusal as refusal:
        raise PhoneError(Refused.of(refusal)) from refusal
    if state_root is not None:
        settings = replace(settings, state_root=state_root)
    clock = clock or SystemClock()
    hub = hub or U2Hub(SubprocessAdb(settings.adb), settings.idle_limit_s, clock)
    chosen: Serial | None = None
    with ExitStack() as stack:
        try:
            ref_device = SnapshotStore(settings.state_root).device_of(ref.snapshot) if ref else None
            chosen = select_device(hub.connected(), Serial(serial) if serial else None, ref_device)
            profile = profile_for(load_profiles(settings.state_root), chosen)
            policy = load_policy(policies, profile)
            stack.enter_context(device_lock(settings, chosen, clock, command))
            phone = hub.open(chosen, first_read)
            stack.callback(phone.close)
            info = phone.info()
            ctx = Context(
                phone,
                info,
                None if profile is None else profile.profile,
                policy,
                SnapshotStore(settings.state_root),
                Ledger(settings.state_root, info.identity),
                clock,
            )
        except Refusal as refusal:
            raise PhoneError(Refused.of(refusal), chosen) from refusal
        yield Driver(ctx, settings.state_root)
