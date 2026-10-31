"""The one place a backend is wired to core, for the CLI and for in-process consumers.

`main()` (`cli/main.py`) parses a command dataclass, opens a `Driver` for one command, runs it and
prints `envelope.to_wire`. A consumer such as
`examples/business_suite/schedule.py` opens one `Driver` for its whole run: it holds the device
lock throughout (A3-4) and pays process start and device facts once.

Wiring order, each step a Refusal on failure:
1. pick the device: `device.select_device(hub.connected(), -d, the ref's device)`;
2. take the device lock `devices/<serial>/lock` (flock; DEVICE_BUSY after the wait budget);
3. open the backend, read `DeviceInfo`;
4. merge policies: package default, then caller files (`rules.merge`). Profile files load with
   the policy engine, in unit 4;
5. build `Context`.

Setup failures arrive as `PhoneError`, like every other failure a consumer sees.
"""

from __future__ import annotations

import tomllib
from collections.abc import Iterator, Sequence
from contextlib import ExitStack, contextmanager
from dataclasses import replace
from pathlib import Path

from agent_phone.adapters.uiautomator2.adb import SubprocessAdb
from agent_phone.adapters.uiautomator2.phone import U2Hub
from agent_phone.cli.settings import Settings
from agent_phone.core.act.intent import Direction
from agent_phone.core.act.ledger import Ledger
from agent_phone.core.commands import snapshot
from agent_phone.core.commands.snapshot import SETTLE_TIMEOUT_MS, SnapshotCommand
from agent_phone.core.context import Context
from agent_phone.core.device import Serial, select_device
from agent_phone.core.outcome import Acted, ErrorCode, Outcome, Read, Refusal, Refused
from agent_phone.core.phone import KeyName, Orientation, PhoneHub
from agent_phone.core.policy.rules import Effect, Policy, merge, parse_policy
from agent_phone.core.query import Query
from agent_phone.core.refs.resolve import Target
from agent_phone.core.refs.store import DeviceLock, SnapshotStore
from agent_phone.core.screen import WindowId
from agent_phone.core.snapshot.snapshot import RefToken, Snapshot
from agent_phone.core.snapshot.surface import Pick
from agent_phone.core.snapshot.view import Mode
from agent_phone.core.wait.clock import Clock, SystemClock
from agent_phone.core.wait.predicate import Predicate

DEFAULT_POLICY = Path(__file__).resolve().parents[1] / "policy" / "default.toml"

TargetLike = Target | RefToken | Query | str


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

    def __init__(self, ctx: Context) -> None:
        self._ctx = ctx

    @property
    def serial(self) -> Serial:
        return self._ctx.info.identity.serial

    def run(self, command: SnapshotCommand) -> Outcome:
        """The one dispatch over command dataclasses, for `main()` and for the typed methods."""
        match command:
            case SnapshotCommand():
                return snapshot.run(self._ctx, command)

    def snapshot(
        self,
        mode: Mode = Mode.COMPACT,
        settle: bool = False,
        root: RefToken | None = None,
        timeout_ms: int = SETTLE_TIMEOUT_MS,
        pick: Pick = Pick.ACTIVE,
        window: WindowId | None = None,
    ) -> Snapshot:
        outcome = self.run(SnapshotCommand(mode, settle, pick, window, root, timeout_ms))
        if isinstance(outcome, Read) and isinstance(outcome.payload, Snapshot):
            return outcome.payload
        raise PhoneError(outcome)

    def click(
        self,
        target: TargetLike,
        *,
        long: bool = False,
        commit: Effect | Sequence[Effect] = (),
        wait_for: Predicate | Sequence[Predicate] = (),
        timeout_ms: int = 5000,
    ) -> Acted:
        raise NotImplementedError

    def set_text(
        self, target: TargetLike, text: str, *, wait_for: Predicate | Sequence[Predicate] = ()
    ) -> Acted:
        raise NotImplementedError

    def scroll(
        self,
        direction: Direction,
        target: TargetLike | None = None,
        *,
        wait_for: Predicate | Sequence[Predicate] = (),
    ) -> Acted:
        raise NotImplementedError

    def press(
        self,
        key: KeyName,
        *,
        commit: Effect | Sequence[Effect] = (),
        wait_for: Predicate | Sequence[Predicate] = (),
    ) -> Acted:
        raise NotImplementedError

    def launch(self, package: str, *, wait_for: Predicate | Sequence[Predicate] = ()) -> Acted:
        raise NotImplementedError

    def stop(self, package: str, *, wait_for: Predicate | Sequence[Predicate] = ()) -> Acted:
        raise NotImplementedError

    def open_uri(
        self,
        uri: str,
        package: str | None = None,
        *,
        commit: Effect | Sequence[Effect] = (),
        wait_for: Predicate | Sequence[Predicate] = (),
    ) -> Acted:
        raise NotImplementedError

    def rotate(self, orientation: Orientation, *, wait_for: Predicate | Sequence[Predicate] = ()) -> Acted:
        raise NotImplementedError

    def wait(self, *predicates: Predicate, timeout_ms: int = 10_000) -> Snapshot:
        raise NotImplementedError

    def screenshot(self, path: Path) -> Read:
        raise NotImplementedError


def load_policy(extra: Sequence[Path]) -> Policy:
    layers = []
    for path in (DEFAULT_POLICY, *extra):
        try:
            document = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as error:
            raise Refusal(
                ErrorCode.POLICY_INVALID,
                f"The policy file {path} cannot be read as TOML: {error}.",
                {"source": str(path)},
            ) from error
        layers.append(parse_policy(document, str(path)))
    return merge(tuple(layers))


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
) -> Iterator[Driver]:
    """`with open_phone("0a1b2c3d4e5f6a7b", policies=[here / "policy.toml"]) as phone: ...`

    The device lock is held until the block ends, and the phone is closed then. `hub`, `settings`
    and `clock` are for tests and for consumers that bring their own; the defaults read the
    environment and use adb.
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
            chosen = select_device(hub.connected(), Serial(serial) if serial else None, None)
            stack.enter_context(device_lock(settings, chosen, clock, command))
            phone = hub.open(chosen)
            stack.callback(phone.close)
            info = phone.info()
            ctx = Context(
                phone,
                info,
                None,
                load_policy(policies),
                SnapshotStore(settings.state_root),
                Ledger(settings.state_root, info.identity),
                clock,
            )
        except Refusal as refusal:
            raise PhoneError(Refused.of(refusal), chosen) from refusal
        yield Driver(ctx)
