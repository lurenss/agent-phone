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
from agent_phone.core.query import Query
from agent_phone.core.refs.fingerprint import Fingerprint
from agent_phone.core.refs.store import SnapshotStore
from agent_phone.core.screen import NodeId, Screen
from agent_phone.core.snapshot.snapshot import RefToken, Snapshot, SnapshotId


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
    # TODO:
    #   snap = store.load(id) for Ref/Point, store.latest(device.serial) for Query and None
    #     (no latest -> OBSERVE_FIRST)
    #   snap.device.serial != device.serial -> WRONG_DEVICE (details: the ref's device)
    #   snap.device.boot_id != device.boot_id -> STALE_REF(REBOOTED)
    #   snap.epoch != epoch -> STALE_REF(SPENT) or OBSERVE_FIRST for Query
    raise NotImplementedError


def locate(target: Target, observed: Snapshot, screen: Screen) -> Resolved:
    """Check 2. Searches every window of the stored package, not only the active one, so an
    element now under a dialog resolves and is then refused as OCCLUDED, not as STALE_REF.
    Raises `Refusal`."""
    # TODO, for RefTarget:
    #   fp = observed.fingerprints.get(n) or NOT_FOUND ("e<n> is not in snapshot <id>")
    #   live = [m for m in nodes of windows with fp.key.package if key_of(m) == fp.key
    #           and (fp.native_id is None or m.native_id in (None, fp.native_id))]
    #   fp.twin is None: 0 -> STALE_REF(GONE), 1 -> it, >1 -> AMBIGUOUS_TARGET (a twin appeared)
    #   fp.twin set: [m.bounds for m in live] == fp.twin.bounds -> live[fp.twin.ordinal]
    #                else AMBIGUOUS_TARGET
    # QueryTarget: matches() over the active window; 0 -> NOT_FOUND, >1 -> AMBIGUOUS_TARGET
    #   with the candidates as refs of a snapshot recorded for the purpose.
    # PointTarget: hit.receiver_at(active window, point); None -> the point itself is the
    #   target with no receiver, which the engine judges as Clear(NO_RECEIVER).
    raise NotImplementedError
