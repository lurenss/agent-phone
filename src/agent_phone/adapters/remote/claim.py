"""This computer's lease on one phone of a phone host: taken, kept and let go.

The host grants a lease to a holder until a deadline (`host/phone_host.py`). The holder here is
the state root: a random id in `<state root>/remote/holder`, written once. Every process that
shares a state root is the same holder, and those processes already take turns on the device lock
(`core/refs/store.py`). Two computers, or two state roots on one computer, are two holders, and
the host lets one of them in.

A claim never trusts an old grant. `keep` runs before every read and input. It asks the host again
once a third of the lease has passed, so the lease cannot run out while it is in use, and it
refuses when the host says the tenure is no longer this holder's.
"""

from __future__ import annotations

import os
import secrets
import time
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path

from agent_phone.adapters.remote.link import Link
from agent_phone.adapters.remote.wire import Busy, Grant, lease_words, parse_grant, release_words
from agent_phone.core.device import Lease, Serial
from agent_phone.core.outcome import ErrorCode, Refusal
from agent_phone.core.wait.clock import Clock
from agent_phone.core.wait.until import until

TTL_S = 120
"""Also how long a phone stays taken after a crash, and after the last command of a job at the
command line."""
RENEW_AFTER_S = TTL_S / 3
"""A third leaves room for the longest single call, the 60 s push of the server jar."""
BUSY_POLL_S = 1.0


def holder_id(state_root: Path) -> str:
    """Read `<state root>/remote/holder`, or create it with 16 random hex characters. Two
    processes that create it at once end with the same id: the file is written whole under another
    name and linked into place, and the loser reads the winner's."""
    path = state_root / "remote" / "holder"
    if not path.exists():
        state_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        path.parent.mkdir(mode=0o700, exist_ok=True)
        temporary = path.with_name(f".holder.{os.getpid()}.tmp")
        temporary.write_text(secrets.token_hex(8) + "\n")
        with suppress(FileExistsError):
            os.link(temporary, path)
        temporary.unlink()
    return path.read_text().strip()


class Claim:
    def __init__(
        self,
        link: Link,
        serial: Serial,
        holder: str,
        task: str,
        device_port: int,
        linger: bool,
        clock: Clock,
        wait_s: float,
        wall: Callable[[], float] = time.time,
    ) -> None:
        """`wall` measures the age of a grant. It is the wall clock because Python's monotonic
        clock on macOS is `mach_absolute_time`, which stops while the computer sleeps. A laptop
        that slept through its deadline must ask again before it sends anything."""
        self._link = link
        self._serial = serial
        self._words = lease_words(serial, holder, task, TTL_S, device_port)
        self._release = release_words(serial, holder)
        self._linger = linger
        self._clock = clock
        self._wait_s = wait_s
        self._wall = wall
        self._grant: Grant | None = None
        self._granted_at = 0.0
        self._port: int | None = None
        self._lost: Refusal | None = None

    @property
    def local_port(self) -> int:
        if self._port is None:
            raise Refusal(ErrorCode.INTERNAL, f"No lease on {self._serial} is held, so no port reaches it.")
        return self._port

    def take(self) -> None:
        seen: list[Lease] = []

        def attempt() -> Grant | None:
            asked = self._wall()
            answer = self._ask()
            if isinstance(answer, Busy):
                seen[:] = [answer.lease]
                return None
            self._granted_at = asked
            return answer

        self._grant = until(self._clock, attempt, self._wait_s, BUSY_POLL_S)
        if self._grant is None:
            raise self._busy(seen[0], f"This command waited {self._wait_s:g} s.", {"waited_s": self._wait_s})
        self._port = self._link.forward(self._grant.host_port)

    def keep(self) -> None:
        if self._lost is not None:
            raise self._lost
        if self._grant is None:
            raise Refusal(ErrorCode.INTERNAL, f"No lease on {self._serial} was taken.")
        asked = self._wall()
        if 0 <= asked - self._granted_at < RENEW_AFTER_S:
            return
        answer = self._ask()
        if isinstance(answer, Busy):
            self._lost = self._busy(
                answer.lease, "This computer's lease ran out first. Open the phone again."
            )
        elif answer.tenure != self._grant.tenure:
            self._lost = Refusal(
                ErrorCode.DEVICE_BUSY,
                f"This computer's lease on {self._serial} ran out, and another holder had the phone since. "
                "What this process read is old. Open the phone again.",
                {"serial": self._serial},
            )
        elif answer.host_port != self._grant.host_port:
            self._lost = Refusal(
                ErrorCode.TRANSPORT,
                f"The phone host moved the port that reaches {self._serial}. Its adb server may have "
                "started again. Open the phone again.",
                {"serial": self._serial},
            )
        if self._lost is not None:
            raise self._lost
        self._granted_at = asked
        self._link.refresh()

    def drop(self) -> None:
        """Best effort: a release that fails is a lease that runs out in `TTL_S`."""
        if self._grant is not None and not self._linger:
            with suppress(Refusal):
                self._link.ask(self._release)
        self._grant = self._port = None

    def _ask(self) -> Grant | Busy:
        return parse_grant(self._link.ask(self._words), self._serial)

    def _busy(self, lease: Lease, then: str, more: dict[str, object] | None = None) -> Refusal:
        task = lease.task or "no task named"
        return Refusal(
            ErrorCode.DEVICE_BUSY,
            f"{lease.by} is driving {self._serial} ({task}). The lease runs out in {lease.free_in_s} s "
            f"unless {lease.by} renews it. {then}",
            {"serial": self._serial, "by": lease.by, "task": lease.task, "free_in_s": lease.free_in_s}
            | (more or {}),
        )
