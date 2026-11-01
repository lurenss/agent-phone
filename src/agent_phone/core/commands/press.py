"""`agent-phone press back|home|recents|enter [--commit ...] [--wait-for ...]`.
The default policy maps `enter` to SEND, so a blind Enter cannot submit a message."""

from __future__ import annotations

from dataclasses import dataclass

from agent_phone.core.act.act import act
from agent_phone.core.act.intent import Request
from agent_phone.core.context import Context
from agent_phone.core.outcome import Outcome
from agent_phone.core.phone import Key, KeyName
from agent_phone.core.policy.engine import Grant
from agent_phone.core.policy.rules import Effect
from agent_phone.core.wait.predicate import Predicate


@dataclass(frozen=True, slots=True)
class PressCommand:
    key: KeyName
    commit: frozenset[Effect] = frozenset()
    wait_for: tuple[Predicate, ...] = ()
    timeout_ms: int = 5000


def run(ctx: Context, cmd: PressCommand) -> Outcome:
    return act(ctx, Request(Key(cmd.key), Grant(cmd.commit), cmd.wait_for, cmd.timeout_ms))
