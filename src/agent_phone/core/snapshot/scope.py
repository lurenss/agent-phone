"""What a read looks at, and the one way every observing command reads it.

A scope names the window (`pick` or a window id) or the subtree (`root`, a ref) that a command
describes. `look` reads the screen for it, once or until it settles, and finds the root again
on that same read, so no command describes a ref it did not just see.
"""

from __future__ import annotations

from dataclasses import dataclass

from agent_phone.core.context import Context
from agent_phone.core.refs.resolve import RefTarget, locate, observed_snapshot
from agent_phone.core.screen import NodeId, Screen, WindowId
from agent_phone.core.snapshot.snapshot import RefToken, SettleState
from agent_phone.core.snapshot.surface import Pick
from agent_phone.core.wait.observe import SETTLE_DEADLINE_S, observe
from agent_phone.core.wait.predicate import Settled

SETTLE_TIMEOUT_MS = int(SETTLE_DEADLINE_S * 1000)


@dataclass(frozen=True, slots=True)
class Scope:
    """At most one of `window` and `root` is set, and `pick` stays ACTIVE with either. The CLI
    enforces that, because the three are ways to answer the same question."""

    pick: Pick = Pick.ACTIVE
    window: WindowId | None = None
    root: RefToken | None = None


@dataclass(frozen=True, slots=True)
class Look:
    """`root` is the node the scope's ref resolved to on `screen`, or None without a ref."""

    screen: Screen
    settled: SettleState
    root: NodeId | None


def look(ctx: Context, scope: Scope, settle: bool = False, timeout_ms: int = SETTLE_TIMEOUT_MS) -> Look:
    """Raise `Refusal`. The ref is checked before the phone is read, and found again after.

    With `settle`, read until every read for `SETTLE_QUIET_S` prints the same lines of the scope's
    surface, or until `timeout_ms` has passed. A timeout is not an error: the last read is
    returned and `settled` says `unsettled`.
    """
    target = None if scope.root is None else RefTarget(scope.root)
    observed = None
    if target is not None:
        observed = observed_snapshot(target, ctx.store, ctx.info.identity, ctx.ledger.epoch())
    if settle:
        seen = observe(ctx, (Settled(scope.pick, scope.window),), ctx.clock.now() + timeout_ms / 1000)
        screen, settled = seen.screen, seen.settled
    else:
        screen, settled = ctx.phone.read(), SettleState.UNCHECKED
    root = None
    if target is not None and observed is not None:
        root = locate(target, observed, screen).node
    return Look(screen, settled, root)
