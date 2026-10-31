"""The live element behind a ref, for the commands that read one property of it.

`get` and `is` answer from the screen as it is now, not from the snapshot that printed the ref,
so they resolve the ref in the two checks of `resolve.py` before they say anything.
"""

from __future__ import annotations

from agent_phone.core.context import Context
from agent_phone.core.refs.resolve import RefTarget, locate, observed_snapshot
from agent_phone.core.screen import Node, Screen
from agent_phone.core.snapshot.snapshot import RefToken


def live_node(ctx: Context, token: RefToken) -> tuple[Screen, Node]:
    """Raise `Refusal`: the observation is checked before the phone is read, and the element is
    found again on the read, strictly."""
    target = RefTarget(token)
    observed = observed_snapshot(target, ctx.store, ctx.info.identity, ctx.ledger.epoch())
    screen = ctx.phone.read()
    return screen, screen.node(locate(target, observed, screen).node)
