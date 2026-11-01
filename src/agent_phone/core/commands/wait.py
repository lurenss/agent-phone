"""`agent-phone wait [--for QUERY]... [--gone QUERY]... [--app PACKAGE] [--settled]
[--timeout-ms N]`. Read-only: it reads the screen until every condition holds on one read and
returns that read as a snapshot. A timeout is TIMEOUT with the last screen read in `details.after`.
A read with no window holds no condition and is read again, so a wait whose every read had no window
ends with NO_SURFACE at its deadline. Either way nothing is sent, so it spends no permit and a retry
is safe."""

from __future__ import annotations

from dataclasses import dataclass

from agent_phone.core.act.act import record
from agent_phone.core.context import Context
from agent_phone.core.outcome import ErrorCode, Outcome, Read, Refusal, Refused
from agent_phone.core.snapshot.capture import capture
from agent_phone.core.wait.observe import observe
from agent_phone.core.wait.predicate import Predicate, describe

WAIT_TIMEOUT_MS = 10_000


@dataclass(frozen=True, slots=True)
class WaitCommand:
    predicates: tuple[Predicate, ...]
    timeout_ms: int = WAIT_TIMEOUT_MS


def require_condition(predicates: tuple[Predicate, ...]) -> None:
    """Raise INVALID_ARGS for no condition: `all` of nothing holds, so the wait would return the
    first read as if something had been waited for."""
    if not predicates:
        raise Refusal(
            ErrorCode.INVALID_ARGS,
            "Wait needs at least one condition: a query that shows or goes, a foreground app, or a "
            "settled screen.",
        )


def run(ctx: Context, cmd: WaitCommand) -> Outcome:
    """Like `snapshot`, it reads the screen itself and needs no snapshot taken before it. The
    snapshot it records is at the ledger's current epoch, so its refs serve the next command."""
    try:
        require_condition(cmd.predicates)
        seen = observe(ctx, cmd.predicates, ctx.clock.now() + cmd.timeout_ms / 1000)
        if seen.held:
            return Read(capture(ctx, seen.screen, settled=seen.settled))
        wanted = " and ".join(describe(p) for p in cmd.predicates)
        together = " on one read" if len(cmd.predicates) > 1 else ""
        return Refused(
            ErrorCode.TIMEOUT,
            f"{wanted} did not hold{together} within {cmd.timeout_ms} ms.",
            {"after": record(ctx, seen.screen, seen.settled)},
        )
    except Refusal as refusal:
        return Refused.of(refusal)
