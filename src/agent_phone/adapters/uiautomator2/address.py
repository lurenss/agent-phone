"""Turning a core `NodeAddress` into a UiSelector that matches that one node on the device.

`setText` and `clearTextField` take a selector, and the server resolves it on its own side,
after core resolved the node on a dump. The two must agree, so before writing this module
proves on the device that the selector reaches a node with the same bounds:

    count(selector) == 1 and objInfo(selector).visibleBounds == address.bounds
    else, for k in range(count): objInfo(selector + instance=k).visibleBounds == address.bounds
         exactly once -> use instance=k

No node with those bounds is NotSent(STALE_REF), several is NotSent(AMBIGUOUS_TARGET). Two
reads (~35 ms each, A2-3) buy the guarantee that text goes into the field core judged.
"""

from __future__ import annotations

from agent_phone.adapters.uiautomator2.rpc import JsonRpc
from agent_phone.core.phone import NodeAddress, NotSent


def selector_for(address: NodeAddress) -> dict[str, object]:
    """resourceId, className and packageName, plus description when set. Never text: a
    field's text is what is about to change."""
    raise NotImplementedError


def pin(rpc: JsonRpc, address: NodeAddress) -> dict[str, object] | NotSent:
    raise NotImplementedError
