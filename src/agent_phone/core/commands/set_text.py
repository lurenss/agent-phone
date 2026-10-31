"""`agent-phone set-text <target> <text> [--wait-for ...]`. Typing commits nothing; the engine
judges the tap or key that submits it. The field is read back, so a delivered set-text without
a contradiction is VERIFIED (except for secret fields, which are never echoed)."""

from __future__ import annotations

from dataclasses import dataclass

from agent_phone.core.act.act import act
from agent_phone.core.act.intent import Fill, Request
from agent_phone.core.context import Context
from agent_phone.core.outcome import Outcome
from agent_phone.core.refs.resolve import Target
from agent_phone.core.wait.predicate import Predicate


@dataclass(frozen=True, slots=True)
class SetTextCommand:
    target: Target
    text: str
    wait_for: tuple[Predicate, ...] = ()


def run(ctx: Context, cmd: SetTextCommand) -> Outcome:
    return act(ctx, Request(Fill(cmd.target, cmd.text), wait_for=cmd.wait_for))
