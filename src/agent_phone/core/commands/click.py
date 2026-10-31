"""`agent-phone click <target> [--long] [--commit <effect>...] [--wait-for <predicate>...]`

Input commands are thin on purpose: act() is the one pipeline, and a command only maps its own
arguments onto a `Request`. `scroll`, `launch`, `open-url`, `rotate`, `power` and
`clipboard set` have this same shape; `press.py` and `stop.py` show the targetless form.
"""

from __future__ import annotations

from dataclasses import dataclass

from agent_phone.core.act.act import act
from agent_phone.core.act.intent import Click, Request
from agent_phone.core.context import Context
from agent_phone.core.outcome import Outcome
from agent_phone.core.policy.engine import Grant
from agent_phone.core.policy.rules import Effect
from agent_phone.core.refs.resolve import Target
from agent_phone.core.wait.predicate import Predicate


@dataclass(frozen=True, slots=True)
class ClickCommand:
    target: Target
    long: bool = False
    commit: frozenset[Effect] = frozenset()
    wait_for: tuple[Predicate, ...] = ()
    timeout_ms: int = 5000


def run(ctx: Context, cmd: ClickCommand) -> Outcome:
    return act(ctx, Request(Click(cmd.target, cmd.long), Grant(cmd.commit), cmd.wait_for, cmd.timeout_ms))
