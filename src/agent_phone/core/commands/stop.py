"""`agent-phone stop <package> [--wait-for ...]`. A package the device profile protects is
DENIED by the engine (`policy.rules.protect_rules`), not by a check here, so `stop`, a
"Force stop" tap in Settings and any later backend share one rule."""

from __future__ import annotations

from dataclasses import dataclass

from agent_phone.core.act.act import act
from agent_phone.core.act.intent import Request
from agent_phone.core.context import Context
from agent_phone.core.device import Package
from agent_phone.core.outcome import Outcome
from agent_phone.core.phone import Stop
from agent_phone.core.wait.predicate import Predicate


@dataclass(frozen=True, slots=True)
class StopCommand:
    package: Package
    wait_for: tuple[Predicate, ...] = ()
    timeout_ms: int = 5000


def run(ctx: Context, cmd: StopCommand) -> Outcome:
    return act(ctx, Request(Stop(cmd.package), wait_for=cmd.wait_for, timeout_ms=cmd.timeout_ms))
