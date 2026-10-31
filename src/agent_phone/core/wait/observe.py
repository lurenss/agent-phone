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
from agent_phone.core.wait.predicate import Predicate

SETTLE_DEADLINE_S = 3.0


@dataclass(frozen=True, slots=True)
class Observation:
    """`held` is False when the deadline passed first; `screen` is then the last read."""

    screen: Screen
    held: bool
    reads: int
    settled: SettleState


def observe(ctx: Context, predicates: tuple[Predicate, ...], deadline: float) -> Observation:
    # TODO:
    #   previous = None
    #   loop: current = ctx.phone.read()
    #         if all(holds(p, previous, current)): return Observation(current, True, ...)
    #         if ctx.clock.now() >= deadline: return Observation(current, False, ...)
    #         previous = current; ctx.clock.pause(POLL_GAP_S)
    #   `settled` is SETTLED when a Settled predicate held, UNCHECKED when none was asked.
    raise NotImplementedError
