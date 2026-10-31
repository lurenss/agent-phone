"""Turning one read into a recorded snapshot: surface, view, budget, fingerprints, store.

Every observation a caller receives (the `snapshot` command, `wait`, `find`, an action's
`after`) comes from `capture`, so all of them carry refs that resolve the same way and stamp
the same epoch.
"""

from __future__ import annotations

from agent_phone.core.context import Context
from agent_phone.core.screen import NodeId, Screen, WindowId
from agent_phone.core.snapshot.snapshot import SettleState, Snapshot
from agent_phone.core.snapshot.view import Mode


def capture(
    ctx: Context,
    screen: Screen,
    mode: Mode = Mode.COMPACT,
    settled: SettleState = SettleState.UNCHECKED,
    window: WindowId | None = None,
    root: NodeId | None = None,
) -> Snapshot:
    # TODO:
    #   surface = select_surface(screen, window, root)
    #   id = ctx.store.new_id(ctx.info.identity.serial)
    #   view = fit(build_view(surface, mode), id)
    #   snap = Snapshot(id, ctx.info.identity, ctx.ledger.epoch(), ..., lines=view.lines,
    #                   fingerprints=fingerprints(view), truncated=...)
    #   ctx.store.record(snap); return snap
    raise NotImplementedError
