"""`agent-phone wait <predicate>... [--timeout-ms N]`. Read-only: a timeout is TIMEOUT with
disposition not_delivered, and the last read is returned as a snapshot either way."""

from __future__ import annotations

from dataclasses import dataclass

from agent_phone.core.context import Context
from agent_phone.core.outcome import Outcome
from agent_phone.core.wait.predicate import Predicate


@dataclass(frozen=True, slots=True)
class WaitCommand:
    predicates: tuple[Predicate, ...]
    timeout_ms: int = 10_000


def run(ctx: Context, cmd: WaitCommand) -> Outcome:
    # TODO: obs = observe(ctx, cmd.predicates, deadline); snap = capture(ctx, obs.screen, ...)
    #   held -> Read(snap); else Refused(TIMEOUT, details={"after": snap})
    raise NotImplementedError
