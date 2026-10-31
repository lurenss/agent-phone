"""`agent-phone snapshot [--compact|--skeleton|--full] [--settle] [--window N] [--root <ref>]`"""

from __future__ import annotations

from dataclasses import dataclass

from agent_phone.core.context import Context
from agent_phone.core.outcome import ErrorCode, Outcome, Read, Refusal, Refused
from agent_phone.core.screen import WindowId
from agent_phone.core.snapshot.capture import capture
from agent_phone.core.snapshot.snapshot import RefToken, SettleState
from agent_phone.core.snapshot.view import Mode


@dataclass(frozen=True, slots=True)
class SnapshotCommand:
    mode: Mode = Mode.COMPACT
    settle: bool = False
    window: WindowId | None = None
    root: RefToken | None = None


def run(ctx: Context, cmd: SnapshotCommand) -> Outcome:
    try:
        if cmd.settle or cmd.root is not None:
            raise Refusal(ErrorCode.NOT_SUPPORTED, "snapshot --settle and --root are not built yet.")
        screen = ctx.phone.read()
        return Read(capture(ctx, screen, cmd.mode, SettleState.UNCHECKED, cmd.window))
    except Refusal as refusal:
        return Refused.of(refusal)
