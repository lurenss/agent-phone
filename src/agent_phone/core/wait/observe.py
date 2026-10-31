"""Reading until a condition holds, and recording what was seen.

`observe` is the only loop that reads the device repeatedly. The `wait` command, `snapshot
--settle`, act()'s auto-wait and act-then-wait all call it, so polling, deadlines and the
settle rule exist once.
"""

from __future__ import annotations

from dataclasses import dataclass

from agent_phone.core.context import Context
from agent_phone.core.screen import Screen
from agent_phone.core.snapshot.snapshot import SettleState
from agent_phone.core.wait.clock import POLL_GAP_S
from agent_phone.core.wait.predicate import Predicate, Settled, holds

SETTLE_DEADLINE_S = 3.0


@dataclass(frozen=True, slots=True)
class Observation:
    """`held` is False when the deadline passed first; `screen` is then the last read."""

    screen: Screen
    held: bool
    reads: int
    settled: SettleState


def observe(ctx: Context, predicates: tuple[Predicate, ...], deadline: float) -> Observation:
    """Read the screen until every predicate holds or `ctx.clock` reaches `deadline`. It reads at
    least once, so a deadline that is already past returns the one read it made.

    `settled` is SETTLED when a Settled predicate held, UNSETTLED when one was asked for and the
    deadline came first, and UNCHECKED when none was asked.
    """
    asked = any(isinstance(p, Settled) for p in predicates)
    previous = None
    reads = 0
    while True:
        current = ctx.phone.read()
        reads += 1
        held = all(holds(p, previous, current) for p in predicates)
        if held or ctx.clock.now() >= deadline:
            settled = SettleState.UNCHECKED
            if asked:
                settled = SettleState.SETTLED if held else SettleState.UNSETTLED
            return Observation(current, held, reads, settled)
        previous = current
        ctx.clock.pause(POLL_GAP_S)
