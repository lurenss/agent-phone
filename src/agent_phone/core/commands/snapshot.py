"""`agent-phone snapshot [--compact|--skeleton|--full] [--settle] [--window N] [--root <ref>]`"""

from __future__ import annotations

from dataclasses import dataclass

from agent_phone.core.context import Context
from agent_phone.core.outcome import Outcome, Read, Refusal, Refused
from agent_phone.core.screen import WindowId
from agent_phone.core.snapshot.snapshot import RefToken
from agent_phone.core.snapshot.view import Mode


@dataclass(frozen=True, slots=True)
class SnapshotCommand:
    mode: Mode = Mode.COMPACT
    settle: bool = False
    window: WindowId | None = None
    root: RefToken | None = None


def run(ctx: Context, cmd: SnapshotCommand) -> Outcome:
    try:
        # TODO: screen = observe(ctx, (Settled(),), deadline).screen if cmd.settle else ctx.phone.read()
        #   root: observed_snapshot + locate the ref on this screen (a drill-down is a new
        #   snapshot of the same surface, numbered the same way)
        #   return Read(capture(ctx, screen, cmd.mode, settled, cmd.window, root_node))
        raise NotImplementedError
    except Refusal as refusal:
        return Refused.of(refusal)
    _ = Read
