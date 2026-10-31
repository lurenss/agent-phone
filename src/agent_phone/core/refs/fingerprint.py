"""What a ref stores so the element can be found again, and nothing else.

Identity is a `Key`: where the element lives (package, window kind), what it is (role, class,
resource-id), what it stably says (`labels.stable_name`) and, inside a collection, which row it
is in (`RowKey`, the stable labels of that row). The key is compared whole. No field is ever
enough alone:

- a resource-id repeats across the rows of a list (four and six times in two of the redacted
  fixtures), so the row's labels separate them;
- a field's text changes as it is typed, so a field's key holds its hint and description only;
- Compose and WebView nodes often have no resource-id, so name and row carry them.

When two nodes on the snapshot's surface share a key, the ref also stores `Twin`: its ordinal
among them and the bounds of all of them. Position is accepted as identity only while the
whole twin set is geometrically unchanged. Otherwise resolution answers AMBIGUOUS_TARGET.
That one rule also covers nameless icons, whose keys collide most: they resolve only on an
unchanged screen.

`path` and `bounds` are locator hints and a stability shortcut, never identity.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from agent_phone.core.device import Package
from agent_phone.core.geometry import Rect
from agent_phone.core.role import Role
from agent_phone.core.screen import Node, Screen, WindowKind
from agent_phone.core.snapshot.view import View

RowKey = tuple[str, ...]
ROW_LABELS = 4


@dataclass(frozen=True, slots=True)
class Key:
    package: Package
    window_kind: WindowKind
    role: Role
    class_name: str
    resource_id: str
    name: str | None
    row: RowKey | None


@dataclass(frozen=True, slots=True)
class Twin:
    ordinal: int
    bounds: tuple[Rect, ...]


@dataclass(frozen=True, slots=True)
class Fingerprint:
    """`native_id` comes from backends with Capability.NODE_IDS. When both sides have one it
    must match too, on top of the key."""

    key: Key
    native_id: str | None
    twin: Twin | None
    bounds: Rect
    path: tuple[int, ...]


def row_key(screen: Screen, node: Node) -> RowKey | None:
    # TODO: find the nearest ancestor whose role is in COLLECTIONS; the row is its child that
    # contains `node`. Return the first ROW_LABELS stable names in the row's subtree in
    # pre-order, or None when there is no collection ancestor.
    raise NotImplementedError


def key_of(screen: Screen, node: Node) -> Key:
    raise NotImplementedError


def fingerprints(view: View) -> Mapping[int, Fingerprint]:
    # TODO: key every node of the surface window once (not only the printed ones, because a
    # live twin need not have been printed); group by key; for each printed ref whose group has
    # more than one node, attach Twin(ordinal in pre-order, bounds of the whole group).
    raise NotImplementedError
