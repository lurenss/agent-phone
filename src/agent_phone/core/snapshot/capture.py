"""Turning one read into a recorded snapshot: surface, view, budget, fingerprints, store.

Every observation a caller receives (the `snapshot` command, `wait`, `find`, an action's
`after`) comes from here, so all of them carry refs that resolve the same way and stamp
the same epoch.
"""

from __future__ import annotations

from agent_phone.core.context import Context
from agent_phone.core.refs.fingerprint import fingerprints
from agent_phone.core.screen import NodeId, Screen, WindowId
from agent_phone.core.snapshot.budget import fit
from agent_phone.core.snapshot.snapshot import SettleState, Snapshot, SnapshotId
from agent_phone.core.snapshot.surface import Pick, Surface, select_surface
from agent_phone.core.snapshot.view import Mode, View, build_view


def capture(
    ctx: Context,
    screen: Screen,
    mode: Mode = Mode.COMPACT,
    settled: SettleState = SettleState.UNCHECKED,
    window: WindowId | None = None,
    root: NodeId | None = None,
    pick: Pick = Pick.ACTIVE,
) -> Snapshot:
    surface = select_surface(screen, window, root, pick)
    id = ctx.store.new_id(ctx.info.identity.serial)
    built = build_view(surface, mode)
    view = fit(built, id)
    return record(ctx, id, surface, view, settled, len(built.lines) - len(view.lines))


def record(
    ctx: Context, id: SnapshotId, surface: Surface, view: View, settled: SettleState, truncated: int
) -> Snapshot:
    """Fingerprint the refs of `view`, stamp the ledger epoch and store the snapshot. `truncated`
    is the number of lines that did not make it into `view`."""
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
        toasts=surface.screen.toasts,
        lines=view.lines,
        fingerprints=fingerprints(view),
        truncated=truncated,
    )
    ctx.store.record(snapshot)
    return snapshot
