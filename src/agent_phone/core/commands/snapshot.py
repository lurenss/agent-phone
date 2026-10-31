"""`agent-phone snapshot [--compact|--skeleton|--full] [--settle [--timeout-ms N]]
[--surface active|dialog|keyboard|shade|all | --window N | --root <ref>]`"""

from __future__ import annotations

from dataclasses import dataclass

from agent_phone.core.context import Context
from agent_phone.core.outcome import Outcome, Read, Refusal, Refused
from agent_phone.core.refs.resolve import RefTarget, locate, observed_snapshot
from agent_phone.core.screen import WindowId
from agent_phone.core.snapshot.capture import capture
from agent_phone.core.snapshot.snapshot import RefToken, SettleState
from agent_phone.core.snapshot.surface import Pick
from agent_phone.core.snapshot.view import Mode
from agent_phone.core.wait.observe import SETTLE_DEADLINE_S, observe
from agent_phone.core.wait.predicate import Settled

SETTLE_TIMEOUT_MS = int(SETTLE_DEADLINE_S * 1000)


@dataclass(frozen=True, slots=True)
class SnapshotCommand:
    mode: Mode = Mode.COMPACT
    settle: bool = False
    pick: Pick = Pick.ACTIVE
    window: WindowId | None = None
    root: RefToken | None = None
    timeout_ms: int = SETTLE_TIMEOUT_MS


def run(ctx: Context, cmd: SnapshotCommand) -> Outcome:
    """With `settle`, read until two consecutive reads print the same lines, or until
    `timeout_ms` has passed. A timeout is not an error: the last read is described and its
    snapshot says `unsettled`.

    With `root`, the ref is checked first (`observed_snapshot`), and then found again on the
    read that is described, so a drill-down never describes an element it did not just see.
    The result is a new snapshot, and the one that held the ref stays valid.
    """
    try:
        target = None if cmd.root is None else RefTarget(cmd.root)
        observed = None
        if target is not None:
            observed = observed_snapshot(target, ctx.store, ctx.info.identity, ctx.ledger.epoch())
        if cmd.settle:
            seen = observe(ctx, (Settled(cmd.pick, cmd.window),), ctx.clock.now() + cmd.timeout_ms / 1000)
            screen, settled = seen.screen, seen.settled
        else:
            screen, settled = ctx.phone.read(), SettleState.UNCHECKED
        root = None
        if target is not None and observed is not None:
            root = locate(target, observed, screen).node
        return Read(capture(ctx, screen, cmd.mode, settled, cmd.window, root, cmd.pick))
    except Refusal as refusal:
        return Refused.of(refusal)
