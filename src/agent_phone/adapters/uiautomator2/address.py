"""Turning a core `NodeAddress` into a UiSelector that matches that one node on the device.

`setText` takes a selector, and the server resolves it on its own side, after core resolved the
node on a dump. The two must agree, so before writing this module proves on the device that the
selector reaches a node with the same bounds:

    count(selector) nodes match; objInfo(selector + instance=k) has the address's bounds
    exactly once -> use instance=k

No node with those bounds is NotSent(STALE_REF), several is NotSent(AMBIGUOUS_TARGET). Two
reads (~35 ms each, A2-3) buy the guarantee that text goes into the field core judged.

The selector that is sent always carries `instance`, also when it is 0. Without it the server's
`setText` taps the center of the first node a `BySelector` finds and types there, and with it
the server only performs ACTION_SET_TEXT on the node the instance names (A2-12).
"""

from __future__ import annotations

from agent_phone.adapters.uiautomator2.rpc import JsonRpc, Phase
from agent_phone.core.geometry import Rect
from agent_phone.core.outcome import ErrorCode
from agent_phone.core.phone import NodeAddress, NotSent

MASKS = {
    "className": 0x10,
    "description": 0x40,
    "packageName": 0x080000,
    "resourceId": 0x200000,
    "instance": 0x01000000,
}
"""The mask bit of each UiSelector field, as uiautomator2's `Selector` sets them."""


def selector_for(address: NodeAddress, instance: int | None = None) -> dict[str, object]:
    """resourceId, className and packageName, plus description when set. Never text: a
    field's text is what is about to change."""
    fields: dict[str, object] = {"className": address.class_name, "packageName": address.package}
    if address.resource_id:
        fields["resourceId"] = address.resource_id
    if address.content_desc:
        fields["description"] = address.content_desc
    if instance is not None:
        fields["instance"] = instance
    mask = 0
    for name in fields:
        mask |= MASKS[name]
    return {"mask": mask, "childOrSibling": [], "childOrSiblingSelector": [], **fields}


def pin(rpc: JsonRpc, address: NodeAddress) -> dict[str, object] | NotSent:
    counted = rpc.call("count", [selector_for(address)])
    if counted.phase is not Phase.ANSWERED or not isinstance(counted.result, int):
        return NotSent(
            ErrorCode.SERVER_UNAVAILABLE, "The server did not count the field's matches. Nothing was sent."
        )
    found = []
    for instance in range(counted.result):
        info = rpc.call("objInfo", [selector_for(address, instance)])
        if info.phase is not Phase.ANSWERED or not isinstance(info.result, dict):
            return NotSent(
                ErrorCode.SERVER_UNAVAILABLE, "The server did not describe a match. Nothing was sent."
            )
        if address.bounds in (rect(info.result.get("visibleBounds")), rect(info.result.get("bounds"))):
            found.append(instance)
    if not found:
        return NotSent(ErrorCode.STALE_REF, "No field on the device has the bounds the screen read showed.")
    if len(found) > 1:
        return NotSent(ErrorCode.AMBIGUOUS_TARGET, f"{len(found)} fields on the device have those bounds.")
    return selector_for(address, found[0])


def rect(value: object) -> Rect | None:
    if not isinstance(value, dict):
        return None
    try:
        return Rect(int(value["left"]), int(value["top"]), int(value["right"]), int(value["bottom"]))
    except (KeyError, TypeError, ValueError):
        return None
