"""Turning one read into a recorded snapshot: surface, view, budget, fingerprints, store.

Every observation a caller receives (the `snapshot` command, `wait`, `find`, an action's
`after`) comes from `capture`, so all of them carry refs that resolve the same way and stamp
the same epoch.
"""

from __future__ import annotations

from agent_phone.core.context import Context
from agent_phone.core.refs.fingerprint import fingerprints
from agent_phone.core.screen import NodeId, Screen, WindowId
from agent_phone.core.snapshot.budget import fit
from agent_phone.core.snapshot.snapshot import SettleState, Snapshot
from agent_phone.core.snapshot.surface import select_surface
from agent_phone.core.snapshot.view import Mode, build_view


def capture(
    ctx: Context,
    screen: Screen,
    mode: Mode = Mode.COMPACT,
    settled: SettleState = SettleState.UNCHECKED,
    window: WindowId | None = None,
    root: NodeId | None = None,
) -> Snapshot:
    surface = select_surface(screen, window, root)
    id = ctx.store.new_id(ctx.info.identity.serial)
    built = build_view(surface, mode)
    view = fit(built, id)
    snapshot = Snapshot(
        id=id,
        device=ctx.info.identity,
        epoch=ctx.ledger.epoch(),
        package=surface.window.package,
        window_kind=surface.window.kind,
        mode=view.mode,
        settled=settled,
        keyboard=surface.keyboard,
        dialog=surface.dialog,
        others=surface.others,
        toasts=screen.toasts,
        lines=view.lines,
        fingerprints=fingerprints(view),
        truncated=len(built.lines) - len(view.lines),
    )
    ctx.store.record(snapshot)
    return snapshot
