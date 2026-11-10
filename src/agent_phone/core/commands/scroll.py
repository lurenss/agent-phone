"""`agent-phone scroll <direction> [<target>] [--wait-for ...] [--until QUERY]`. A swipe across the
list, planned inside it and under no other window (`act/hit.py`). `down` shows what is below. With
no target, the active window must hold exactly one element that scrolls.

With `until`, the swipe repeats until a line that matches shows. Each swipe is its own `act()`, so
each is planned on a fresh read, judged and spent like any input, and the screen settles between
two swipes."""

from __future__ import annotations

from dataclasses import dataclass, replace

from agent_phone.core.act.act import act
from agent_phone.core.act.intent import Direction, Request, Scroll
from agent_phone.core.context import Context
from agent_phone.core.outcome import Acted, ErrorCode, Outcome, Refusal, Refused
from agent_phone.core.query import Query
from agent_phone.core.refs.resolve import Target
from agent_phone.core.wait.predicate import Predicate, Present, Settled, describe, holds, printed_lines

MAX_SWIPES = 10
"""A list longer than ten swipes is a feed. The caller reads where it is and asks again."""


@dataclass(frozen=True, slots=True)
class ScrollCommand:
    direction: Direction
    target: Target | None = None
    wait_for: tuple[Predicate, ...] = ()
    timeout_ms: int = 5000
    until: Query | None = None


def run(ctx: Context, cmd: ScrollCommand) -> Outcome:
    request = Request(Scroll(cmd.target, cmd.direction), wait_for=cmd.wait_for, timeout_ms=cmd.timeout_ms)
    if cmd.until is None:
        return act(ctx, request)
    return swipe_until(ctx, Present(cmd.until), replace(request, wait_for=(Settled(),)))


def swipe_until(ctx: Context, shows: Present, request: Request) -> Outcome:
    """The last swipe's outcome, with the settled screen it ended on. NOT_FOUND when the list stopped
    moving or `MAX_SWIPES` went out first, still with that screen. Nothing is sent when the line
    already shows. A swipe that is refused after another went out is reported on the one that went
    out, so the result never says that nothing reached the phone."""
    try:
        screen = ctx.phone.read()
    except Refusal as refusal:
        return Refused.of(refusal)
    if holds(shows, None, screen):
        return Refused(ErrorCode.INVALID_ARGS, f"{describe(shows)} already holds. Nothing was sent.")
    last: Acted | None = None
    swipes = 0
    while True:
        outcome = act(ctx, request)
        if isinstance(outcome, Refused):
            return outcome if last is None else replace(last, error=outcome.code, message=outcome.message)
        if not isinstance(outcome, Acted) or outcome.error is not None:
            return outcome
        last, swipes = outcome, swipes + 1
        try:
            now = ctx.phone.read()
        except Refusal as refusal:
            return replace(last, error=refusal.code, message=refusal.message)
        if holds(shows, None, now):
            return last
        stopped = printed_lines(now, Settled()) == printed_lines(screen, Settled())
        if stopped or swipes == MAX_SWIPES:
            end = ", and the list stopped moving." if stopped else ". Read the screen, then go on."
            message = f"{describe(shows)} did not show after {swipes} swipes{end}"
            return replace(last, error=ErrorCode.NOT_FOUND, message=message)
        screen = now
