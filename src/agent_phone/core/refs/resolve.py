"""From what the caller named to one live node, or a refusal. Never a guess.

Two checks, in this order, both before the phone is touched again:

1. **The observation is current.** A ref or point names its snapshot. A query names the latest
   snapshot of the device. That snapshot must come from this device and this boot
   (WRONG_DEVICE, STALE_REF reason `rebooted`), and from the ledger's current epoch: no input
   may have been sent since it was taken (STALE_REF reason `spent` for refs and points,
   OBSERVE_FIRST for queries). This is what makes a blind retry impossible: after any input
   that may have landed, the same command fails until the caller has looked again.
2. **The element is found exactly once** on the live screen, by the stored key, or by the
   query, or by hit testing the point.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from agent_phone.core.device import DeviceIdentity
from agent_phone.core.geometry import Point
from agent_phone.core.outcome import ErrorCode, Refusal
from agent_phone.core.query import Query, matches
from agent_phone.core.refs.fingerprint import Fingerprint, key_of
from agent_phone.core.refs.store import SnapshotStore
from agent_phone.core.screen import Node, NodeId, Screen
from agent_phone.core.snapshot.snapshot import RefToken, Snapshot, SnapshotId
from agent_phone.core.snapshot.surface import select_surface
from agent_phone.core.snapshot.view import Mode, build_view


@dataclass(frozen=True, slots=True)
class RefTarget:
    token: RefToken


@dataclass(frozen=True, slots=True)
class QueryTarget:
    query: Query


@dataclass(frozen=True, slots=True)
class PointTarget:
    """`@k3x9q:540,1450`: a coordinate, bound to the snapshot the caller read it from."""

    snapshot: SnapshotId
    point: Point


Target = RefTarget | QueryTarget | PointTarget


class StaleReason(Enum):
    SPENT = "spent"
    REBOOTED = "rebooted"
    GONE = "gone"


@dataclass(frozen=True, slots=True)
class Resolved:
    node: NodeId
    observed: Snapshot
    fingerprint: Fingerprint | None


def observed_snapshot(
    target: Target | None, store: SnapshotStore, device: DeviceIdentity, epoch: int
) -> Snapshot:
    """Check 1. Raises `Refusal`. `target` None is an input with no target (a key, a launch,
    a rotation): it too needs a current observation, or "press enter" could be resent blind."""
    match target:
        case RefTarget(token):
            snapshot_id: SnapshotId | None = token.snapshot
        case PointTarget(snapshot):
            snapshot_id = snapshot
        case _:
            snapshot_id = None
    if snapshot_id is not None:
        observed = store.load(snapshot_id)
    else:
        observed = store.latest(device.serial)
        if observed is None:
            raise Refusal(
                ErrorCode.OBSERVE_FIRST,
                f"No snapshot of {device.serial} exists yet. Take one and look first.",
            )
    if observed.device.serial != device.serial:
        raise Refusal(
            ErrorCode.WRONG_DEVICE,
            f"Snapshot {observed.id} belongs to {observed.device.serial}, not {device.serial}.",
            {"ref_device": observed.device.serial},
        )
    if observed.device.boot_id != device.boot_id:
        raise stale(StaleReason.REBOOTED, f"{observed.id} was taken before the phone restarted.")
    if observed.epoch != epoch:
        if snapshot_id is None:
            raise Refusal(
                ErrorCode.OBSERVE_FIRST,
                f"Input was sent since the latest snapshot, {observed.id}. Take a new one and look first.",
            )
        raise stale(StaleReason.SPENT, f"{observed.id} was taken before the last input.")
    return observed


def stale(reason: StaleReason, why: str) -> Refusal:
    return Refusal(
        ErrorCode.STALE_REF,
        f"The ref cannot be trusted: {why} Take a new snapshot and use a ref from it.",
        {"reason": reason.value},
    )


def locate(target: Target, observed: Snapshot, screen: Screen) -> Resolved:
    """Check 2. Searches every window of the stored package, not only the active one, so an
    element now under a dialog resolves and is then refused as OCCLUDED, not as STALE_REF.
    Raises `Refusal`."""
    match target:
        case QueryTarget(query):
            return Resolved(query_match(query, screen), observed, None)
        case PointTarget():
            raise Refusal(
                ErrorCode.NOT_SUPPORTED, "A point is not a target yet. Use a ref, or a query by name or id."
            )
    number = target.token.number
    fingerprint = observed.fingerprints.get(number)
    if fingerprint is None:
        raise Refusal(
            ErrorCode.NOT_FOUND,
            f"e{number} is not in snapshot {observed.id}. Use a ref that the snapshot printed.",
            {"snapshot": observed.id, "number": number},
        )
    live = tuple(node for node in screen.nodes if matches_fingerprint(screen, node, fingerprint))
    if fingerprint.twin is None:
        if not live:
            raise stale(StaleReason.GONE, f"{target.token} is no longer on screen.")
        if len(live) > 1:
            raise ambiguous(target.token, len(live))
        return Resolved(live[0].id, observed, fingerprint)
    if tuple(node.attrs.bounds for node in live) != fingerprint.twin.bounds:
        raise ambiguous(target.token, len(live))
    return Resolved(live[fingerprint.twin.ordinal].id, observed, fingerprint)


def query_match(query: Query, screen: Screen) -> NodeId:
    """The one element of the active window that has a ref in a compact view and matches."""
    view = build_view(select_surface(screen), Mode.COMPACT)
    found = [
        node
        for line, node in zip(view.lines, view.nodes, strict=True)
        if line.ref is not None and matches(query, screen, screen.node(node))
    ]
    if not found:
        raise Refusal(ErrorCode.NOT_FOUND, f"No element on screen matches {query.describe()}.")
    if len(found) > 1:
        raise Refusal(
            ErrorCode.AMBIGUOUS_TARGET,
            f"{len(found)} elements match {query.describe()}. Narrow the query, or use a ref from find.",
            {"matches": len(found)},
        )
    return found[0]


def matches_fingerprint(screen: Screen, node: Node, fingerprint: Fingerprint) -> bool:
    """The cheap fields first, because most nodes of a screen differ from the key in one of them."""
    key, attrs = fingerprint.key, node.attrs
    return (
        attrs.package == key.package
        and attrs.class_name == key.class_name
        and attrs.resource_id == key.resource_id
        and (fingerprint.native_id is None or attrs.native_id in (None, fingerprint.native_id))
        and key_of(screen, node) == key
    )


def ambiguous(token: RefToken, live: int) -> Refusal:
    return Refusal(
        ErrorCode.AMBIGUOUS_TARGET,
        f"{token} now matches {live} elements, so it is not clear which one it was. "
        "Take a new snapshot and use a ref from it.",
        {"matches": live},
    )
