"""Reading until a condition holds, and recording what was seen.

`observe` is the loop that polls the screen for a condition. The `wait` command, `snapshot
--settle` and act-then-wait (`--wait-for`) all call it, so polling, deadlines, empty reads and the
settle rule exist once. act()'s auto-wait for a target polls with `until` and reads on its own.
"""

from __future__ import annotations

from dataclasses import dataclass

from agent_phone.core.context import Context
from agent_phone.core.outcome import ErrorCode, Refusal
from agent_phone.core.screen import Screen
from agent_phone.core.snapshot.snapshot import SettleState
from agent_phone.core.wait.clock import POLL_GAP_S
from agent_phone.core.wait.predicate import Predicate, Settled, holds, is_effect

SETTLE_DEADLINE_S = 3.0
SETTLE_QUIET_S = 0.8
"""How long every read must print the same lines before a screen is settled. Two equal reads 50 ms
apart settled an empty grid before its items loaded (#4)."""


@dataclass(frozen=True, slots=True)
class Observation:
    """`held` is False when the deadline passed first; `screen` is then the last screen read.
    `reads` counts every read the loop made, the empty ones too."""

    screen: Screen
    held: bool
    reads: int
    settled: SettleState


def read_or_empty(ctx: Context) -> Screen | Refusal:
    """The screen, or the `NO_SURFACE` refusal of a dump with no window on the default display, as
    comes between two screens. Any other refusal raises."""
    try:
        return ctx.phone.read()
    except Refusal as refusal:
        if refusal.code is not ErrorCode.NO_SURFACE:
            raise
        return refusal


def observe(ctx: Context, predicates: tuple[Predicate, ...], deadline: float) -> Observation:
    """Read the screen until every predicate holds or `ctx.clock` reaches `deadline`. It reads at
    least once, so a deadline that is already past returns the one read it made.

    A `Settled` holds once its surface has printed the same lines on every read for
    `SETTLE_QUIET_S`. A read that prints other lines starts that window again.

    An empty read (`NO_SURFACE`) is a read on which no predicate holds, so a `Gone` does not hold on
    it either: an empty dump is no evidence that anything left the screen. It also breaks a run of
    equal reads, so settling starts again. The loop reads again after it. Any other refusal ends
    the wait at once.

    At the deadline, `observe` returns `held=False` with the last screen it read. When no read
    produced a screen, it raises the `NO_SURFACE` of the last read instead. So a screen that is off
    reports `NO_SURFACE` after the whole timeout and not on the first read.

    `settled` is SETTLED when a Settled predicate held, UNSETTLED when one was asked for and the
    deadline came first, and UNCHECKED when none was asked.
    """
    settles = [p for p in predicates if isinstance(p, Settled)]
    effects = [p for p in predicates if is_effect(p)]
    previous: Screen | None = None
    last: Screen | None = None
    quiet_since = ctx.clock.now()
    reads = 0
    while True:
        current = read_or_empty(ctx)
        reads += 1
        now = ctx.clock.now()
        expired = now >= deadline
        if isinstance(current, Refusal):
            if expired and last is None:
                raise current
            held, previous = False, None
        else:
            if not all(holds(p, previous, current) for p in settles):
                quiet_since = now
            quiet = not settles or now - quiet_since >= SETTLE_QUIET_S
            held = quiet and all(holds(p, previous, current) for p in effects)
            last = previous = current
        if held or expired:
            settled = SettleState.UNCHECKED
            if settles:
                settled = SettleState.SETTLED if held else SettleState.UNSETTLED
            return Observation(last, held, reads, settled)
        ctx.clock.pause(POLL_GAP_S)
