"""`agent-phone scroll <direction> [<target>] [--wait-for ...]`. A swipe across the list, planned
inside it and under no other window (`act/hit.py`). `down` shows what is below. With no target,
the active window must hold exactly one element that scrolls."""

from __future__ import annotations

from dataclasses import dataclass

from agent_phone.core.act.act import act
from agent_phone.core.act.intent import Direction, Request, Scroll
from agent_phone.core.context import Context
from agent_phone.core.outcome import Outcome
from agent_phone.core.refs.resolve import Target
from agent_phone.core.wait.predicate import Predicate


@dataclass(frozen=True, slots=True)
class ScrollCommand:
    direction: Direction
    target: Target | None = None
    wait_for: tuple[Predicate, ...] = ()
    timeout_ms: int = 5000


def run(ctx: Context, cmd: ScrollCommand) -> Outcome:
    return act(
        ctx, Request(Scroll(cmd.target, cmd.direction), wait_for=cmd.wait_for, timeout_ms=cmd.timeout_ms)
    )
