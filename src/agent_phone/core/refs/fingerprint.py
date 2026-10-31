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

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass

from agent_phone.core.device import Package
from agent_phone.core.geometry import Rect
from agent_phone.core.labels import naming_values, own_labels, stable_name
from agent_phone.core.role import COLLECTIONS, Role, role_of
from agent_phone.core.screen import Node, NodeId, Screen, WindowKind
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
    """The first ROW_LABELS distinct stable labels of the row that holds `node`, in pre-order.
    The row is the child of the nearest collection ancestor that contains `node`; None when
    no ancestor is a collection. Each member contributes its own fields only, so a label
    counts once however many layouts sit around it."""
    row = node
    for ancestor in screen.ancestors(node.id):
        if role_of(ancestor.attrs) in COLLECTIONS:
            break
        row = ancestor
    else:
        return None
    labels: list[str] = []
    for member in screen.subtree(row.id):
        for value in naming_values(screen, own_labels(member)):
            if value not in labels:
                labels.append(value)
                if len(labels) == ROW_LABELS:
                    return tuple(labels)
    return tuple(labels)


def key_of(screen: Screen, node: Node) -> Key:
    attrs = node.attrs
    role = role_of(attrs)
    return Key(
        package=Package(attrs.package),
        window_kind=screen.window_of(node.id).kind,
        role=role,
        class_name=attrs.class_name,
        resource_id=attrs.resource_id,
        name=stable_name(screen, node, role),
        row=row_key(screen, node),
    )


def fingerprints(view: View) -> Mapping[int, Fingerprint]:
    """Every node of the screen is keyed, not only the printed ones, because a live twin need
    not have been printed, and resolution searches every window of the stored package."""
    screen = view.surface.screen
    keys = [key_of(screen, node) for node in screen.nodes]
    groups: dict[Key, list[NodeId]] = defaultdict(list)
    for node, key in zip(screen.nodes, keys, strict=True):
        groups[key].append(node.id)
    printed: dict[int, Fingerprint] = {}
    for ref, id in view.refs.items():
        node = screen.node(id)
        group = groups[keys[id]]
        twin = None
        if len(group) > 1:
            twin = Twin(group.index(id), tuple(screen.node(member).attrs.bounds for member in group))
        printed[ref] = Fingerprint(
            keys[id], node.attrs.native_id, twin, node.attrs.bounds, path_of(screen, node)
        )
    return printed


def path_of(screen: Screen, node: Node) -> tuple[int, ...]:
    """Child indexes from the window root down to `node`."""
    path: list[int] = []
    while node.parent is not None:
        parent = screen.node(node.parent)
        path.append(parent.children.index(node.id))
        node = parent
    return tuple(reversed(path))
