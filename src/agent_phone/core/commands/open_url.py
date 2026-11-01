"""`agent-phone open-url <uri> [--package P] [--commit ...] [--wait-for ...]`

A link opens with the VIEW action. An intent is written as an intent URI that names only an
action and, optionally, a package: `intent:#Intent;action=android.settings.DISPLAY_SETTINGS;end`.
The engine judges a link by its scheme, so `tel:` and `sms:` links need `--commit send`.
"""

from __future__ import annotations

from dataclasses import dataclass

from agent_phone.core.act.act import act
from agent_phone.core.act.intent import Request
from agent_phone.core.context import Context
from agent_phone.core.device import Package
from agent_phone.core.outcome import Outcome, Refusal, Refused
from agent_phone.core.phone import OpenUri, intent_of
from agent_phone.core.policy.engine import Grant
from agent_phone.core.policy.rules import Effect
from agent_phone.core.wait.predicate import Predicate


@dataclass(frozen=True, slots=True)
class OpenUrlCommand:
    uri: str
    package: Package | None = None
    commit: frozenset[Effect] = frozenset()
    wait_for: tuple[Predicate, ...] = ()
    timeout_ms: int = 5000


def run(ctx: Context, cmd: OpenUrlCommand) -> Outcome:
    action = OpenUri(cmd.uri, cmd.package)
    try:
        intent_of(action)
    except Refusal as refusal:
        return Refused.of(refusal)
    return act(ctx, Request(action, Grant(cmd.commit), cmd.wait_for, cmd.timeout_ms))
