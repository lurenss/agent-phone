"""`agent-phone snapshot [--compact|--skeleton|--full] [--settle [--timeout-ms N]]
[--surface active|dialog|keyboard|shade|all | --window N | --root <ref>]`"""

from __future__ import annotations

from dataclasses import dataclass, field

from agent_phone.core.context import Context
from agent_phone.core.outcome import Outcome, Read, Refusal, Refused
from agent_phone.core.snapshot.capture import capture
from agent_phone.core.snapshot.scope import SETTLE_TIMEOUT_MS, Scope, look
from agent_phone.core.snapshot.view import Mode


@dataclass(frozen=True, slots=True)
class SnapshotCommand:
    mode: Mode = Mode.COMPACT
    settle: bool = False
    scope: Scope = field(default_factory=Scope)
    timeout_ms: int = SETTLE_TIMEOUT_MS


def run(ctx: Context, cmd: SnapshotCommand) -> Outcome:
    """The result is a new snapshot. With a `root`, the snapshot that held the ref stays valid."""
    try:
        seen = look(ctx, cmd.scope, cmd.settle, cmd.timeout_ms)
        scope = cmd.scope
        return Read(capture(ctx, seen.screen, cmd.mode, seen.settled, scope.window, seen.root, scope.pick))
    except Refusal as refusal:
        return Refused.of(refusal)
