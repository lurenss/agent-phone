"""The one place a backend is wired to core, for the CLI and for in-process consumers.

`main()` (argument parsing, out of scope here) builds a command dataclass, opens a `Driver` for
one command, runs it and prints `envelope.to_wire`. A consumer such as
`examples/business_suite/schedule.py` opens one `Driver` for its whole run: it holds the device
lock throughout (A3-4) and pays process start and device facts once.

Wiring order, each step a Refusal on failure:
1. pick the device: `device.select_device(hub.connected(), -d, the ref's device)`;
2. take the device lock `devices/<serial>/lock` (flock; DEVICE_BUSY after the wait budget);
3. open the backend, read `DeviceInfo`;
4. load the profile whose serial matches, if any, and merge policies: package default,
   profile protections and files, caller files (`rules.merge`);
5. build `Context`.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path

from agent_phone.cli.settings import Settings
from agent_phone.core.act.intent import Direction
from agent_phone.core.context import Context
from agent_phone.core.device import Package, Serial
from agent_phone.core.outcome import Acted, Outcome, Read
from agent_phone.core.phone import KeyName, Orientation
from agent_phone.core.policy.rules import Effect
from agent_phone.core.query import Query
from agent_phone.core.refs.resolve import Target
from agent_phone.core.refs.store import DeviceLock, SnapshotStore
from agent_phone.core.snapshot.snapshot import RefToken, Snapshot
from agent_phone.core.snapshot.view import Mode
from agent_phone.core.wait.clock import Clock
from agent_phone.core.wait.predicate import Predicate

DEFAULT_POLICY = Path(__file__).resolve().parents[1] / "policy" / "default.toml"
STATE_ROOT = Path.home() / ".agent-phone"

TargetLike = Target | RefToken | Query | str


def device_lock(settings: Settings, serial: Serial, clock: Clock, command: str) -> DeviceLock:
    """The claim on one device for one command or one Driver session (A3-4)."""
    return SnapshotStore(settings.state_root).lock(serial, clock, settings.lock_wait_s, command)


class PhoneError(Exception):
    """Raised by `Driver` methods when the outcome is not ok. `outcome.disposition` says
    whether the consumer may try the same step again."""

    def __init__(self, outcome: Outcome) -> None:
        super().__init__(str(outcome))
        self.outcome = outcome


class Driver:
    """The public API. Each method runs the same `core/commands/<name>.py` function the CLI
    runs, so a consumer cannot reach the device by a path the CLI does not have."""

    def __init__(self, ctx: Context) -> None:
        self._ctx = ctx

    def snapshot(
        self, mode: Mode = Mode.COMPACT, settle: bool = False, root: RefToken | None = None
    ) -> Snapshot:
        raise NotImplementedError

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


@contextmanager
def open_phone(
    serial: str | None = None, policies: Sequence[Path] = (), state_root: Path = STATE_ROOT
) -> Iterator[Driver]:
    """`with open_phone("0a1b2c3d4e5f6a7b", policies=[here / "policy.toml"]) as phone: ...`"""
    _ = (Package, Serial)
    raise NotImplementedError
    yield
