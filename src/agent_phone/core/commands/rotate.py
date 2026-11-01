"""`agent-phone rotate portrait|landscape|auto [--wait-for ...]`. Portrait and landscape lock the
rotation there; auto hands it back to the sensor."""

from __future__ import annotations

from dataclasses import dataclass

from agent_phone.core.act.act import act
from agent_phone.core.act.intent import Request
from agent_phone.core.context import Context
from agent_phone.core.outcome import Outcome
from agent_phone.core.phone import Orientation, Rotate
from agent_phone.core.wait.predicate import Predicate


@dataclass(frozen=True, slots=True)
class RotateCommand:
    orientation: Orientation
    wait_for: tuple[Predicate, ...] = ()
    timeout_ms: int = 5000


def run(ctx: Context, cmd: RotateCommand) -> Outcome:
    return act(ctx, Request(Rotate(cmd.orientation), wait_for=cmd.wait_for, timeout_ms=cmd.timeout_ms))
