"""`agent-phone snapshot [--compact|--skeleton|--full] [--settle [--timeout-ms N]]
[--window N] [--root <ref>]`"""

from __future__ import annotations

from dataclasses import dataclass

from agent_phone.core.context import Context
from agent_phone.core.outcome import ErrorCode, Outcome, Read, Refusal, Refused
from agent_phone.core.screen import WindowId
from agent_phone.core.snapshot.capture import capture
from agent_phone.core.snapshot.snapshot import RefToken, SettleState
from agent_phone.core.snapshot.view import Mode
from agent_phone.core.wait.observe import SETTLE_DEADLINE_S, observe
from agent_phone.core.wait.predicate import Settled

SETTLE_TIMEOUT_MS = int(SETTLE_DEADLINE_S * 1000)


@dataclass(frozen=True, slots=True)
class SnapshotCommand:
    mode: Mode = Mode.COMPACT
    settle: bool = False
    window: WindowId | None = None
    root: RefToken | None = None
    timeout_ms: int = SETTLE_TIMEOUT_MS


def run(ctx: Context, cmd: SnapshotCommand) -> Outcome:
    """With `settle`, read until two consecutive reads print the same lines, or until
    `timeout_ms` has passed. A timeout is not an error: the last read is described and its
    snapshot says `unsettled`."""
    try:
        if cmd.root is not None:
            raise Refusal(ErrorCode.NOT_SUPPORTED, "snapshot --root is not built yet.")
        if cmd.settle:
            seen = observe(ctx, (Settled(),), ctx.clock.now() + cmd.timeout_ms / 1000)
            screen, settled = seen.screen, seen.settled
        else:
            screen, settled = ctx.phone.read(), SettleState.UNCHECKED
        return Read(capture(ctx, screen, cmd.mode, settled, cmd.window))
    except Refusal as refusal:
        return Refused.of(refusal)
