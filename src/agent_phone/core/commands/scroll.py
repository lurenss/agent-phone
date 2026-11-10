"""`agent-phone scroll <direction> [<target>] [--wait-for ...] [--until QUERY]`. A swipe across the
list, planned inside it and under no other window (`act/hit.py`). `down` shows what is below. With
no target, the active window must hold exactly one element that scrolls.

With `until`, the swipe repeats until a line that matches shows. Each swipe is its own `act()`, so
each is planned on a fresh read, judged and spent like any input, and the screen settles between
two swipes."""

from __future__ import annotations

from dataclasses import dataclass, replace

from agent_phone.core.act.act import act, record
from agent_phone.core.act.intent import Direction, Request, Scroll
from agent_phone.core.context import Context
from agent_phone.core.outcome import Acted, ErrorCode, Outcome, Refusal, Refused, SentState
from agent_phone.core.query import Query
from agent_phone.core.refs.resolve import RefTarget, Target
from agent_phone.core.screen import Screen
from agent_phone.core.snapshot.budget import render_line
from agent_phone.core.snapshot.snapshot import SettleState, Snapshot
from agent_phone.core.wait.predicate import (
    SETTLE_ID,
    Predicate,
    Present,
    Settled,
    describe,
    holds,
    is_effect,
    printed_lines,
)

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
    try:
        check_until(cmd.target, cmd.wait_for)
    except Refusal as refusal:
        return Refused.of(refusal)
    return swipe_until(ctx, Present(cmd.until), replace(request, wait_for=(Settled(),)))


def check_until(target: Target | None, wait_for: tuple[Predicate, ...]) -> None:
    """Raise INVALID_ARGS for an `until` that cannot work. The first swipe spends a ref, so a ref
    cannot name the list for the second. The line that shows is the wait, so an effect to wait
    for beside it would be dropped. A `Settled` beside it changes nothing: every swipe settles."""
    if isinstance(target, RefTarget):
        raise Refusal(
            ErrorCode.INVALID_ARGS,
            "--until swipes more than once, and the first swipe spends the ref. Name the list by a "
            "query, such as id=recycler_view, or leave it out when one list scrolls.",
        )
    if any(is_effect(predicate) for predicate in wait_for):
        raise Refusal(
            ErrorCode.INVALID_ARGS, "--until is the wait. Leave out --wait-for and --wait-for-gone."
        )


def swipe_until(ctx: Context, shows: Present, request: Request) -> Outcome:
    """The last swipe's outcome for all of them: `before` is the snapshot the first swipe stood on,
    `sent` is uncertain when any swipe's was, and `inputs` counts the swipes. `after` is the screen
    the line showed on. NOT_FOUND, still with the last screen, when a swipe did not move the list,
    when the screen did not settle, so that its end cannot be told, or after `MAX_SWIPES`. Nothing
    is sent when the line already shows. A swipe that is refused after another went out is reported
    on the one that went out, with the refusal's details, so the result never says that nothing
    reached the phone."""
    try:
        screen = ctx.phone.read()
    except Refusal as refusal:
        return Refused.of(refusal)
    if holds(shows, None, screen):
        return Refused(ErrorCode.INVALID_ARGS, f"{describe(shows)} already holds. Nothing was sent.")
    last: Acted | None = None
    while True:
        outcome = act(ctx, request)
        if not isinstance(outcome, Acted):
            if last is None or not isinstance(outcome, Refused):
                return outcome
            return replace(last, error=outcome.code, message=outcome.message, details=outcome.details)
        uncertain = SentState.UNCERTAIN in (outcome.sent, last.sent if last else None)
        last = replace(
            outcome,
            sent=SentState.UNCERTAIN if uncertain else outcome.sent,
            before=last.before if last else outcome.before,
            inputs=last.inputs + 1 if last else 1,
        )
        if outcome.error is not None:
            return last
        try:
            now = ctx.phone.read()
        except Refusal as refusal:
            return replace(last, error=refusal.code, message=refusal.message, details=refusal.details)
        if holds(shows, None, now):
            return replace(last, after=shown_on(ctx, last.after, now))
        end = None
        if printed_lines(now, Settled()) == printed_lines(screen, Settled()):
            end = ", and the list stopped moving."
        elif last.after is None or last.after.settled is not SettleState.SETTLED:
            end = ", and the screen did not settle, so the end of the list cannot be told."
        elif last.inputs == MAX_SWIPES:
            end = ". Read the screen, then go on."
        if end is not None:
            message = f"{describe(shows)} did not show after {last.inputs} swipes{end}"
            return replace(last, error=ErrorCode.NOT_FOUND, message=message)
        screen = now


def shown_on(ctx: Context, after: Snapshot | None, now: Screen) -> Snapshot | None:
    """The snapshot the caller gets must print the line. `after` was recorded on the settled read
    and the line was found one read later, so when the two print other lines, a row that loaded
    late is in the second only, and that read is recorded in place of `after`, unchecked."""
    if after is not None and tuple(render_line(line, SETTLE_ID) for line in after.lines) == printed_lines(
        now, Settled()
    ):
        return after
    return record(ctx, now, SettleState.UNCHECKED)
