"""`agent-phone launch <package> [--wait-for ...]`. Starts the package's launcher activity. Like
every input it needs a current observation, so a launch cannot be repeated blind."""

from __future__ import annotations

from dataclasses import dataclass

from agent_phone.core.act.act import act
from agent_phone.core.act.intent import Request
from agent_phone.core.context import Context
from agent_phone.core.device import Package
from agent_phone.core.outcome import Outcome
from agent_phone.core.phone import Launch
from agent_phone.core.wait.predicate import Predicate


@dataclass(frozen=True, slots=True)
class LaunchCommand:
    package: Package
    wait_for: tuple[Predicate, ...] = ()
    timeout_ms: int = 5000


def run(ctx: Context, cmd: LaunchCommand) -> Outcome:
    return act(ctx, Request(Launch(cmd.package), wait_for=cmd.wait_for, timeout_ms=cmd.timeout_ms))
