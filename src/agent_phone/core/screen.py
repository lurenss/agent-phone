"""One read of every window on the device, as core types.

Adapters build `WindowSpec` trees (nested, in the order the backend reports children) and call
`Screen.build`. Core owns the flat arena that every later step walks: ids are pre-order indexes,
and a node's subtree is the contiguous slice `nodes[id:end]`. Ancestor walks follow `parent`,
hit tests descend `children`. Nothing after `build` needs a map, an index or a cache.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass, replace
from enum import Enum
from typing import NewType

from agent_phone.core.device import Package
from agent_phone.core.geometry import Point, Rect, Rotation, Size
from agent_phone.core.outcome import ErrorCode, Refusal

NodeId = NewType("NodeId", int)
WindowId = NewType("WindowId", int)


class Flag(Enum):
    CLICKABLE = "clickable"
    LONG_CLICKABLE = "long_clickable"
    SCROLLABLE = "scrollable"
    CHECKABLE = "checkable"
    CHECKED = "checked"
    ENABLED = "enabled"
    FOCUSABLE = "focusable"
    FOCUSED = "focused"
    SELECTED = "selected"
    PASSWORD = "password"
    VISIBLE = "visible"
    EDITABLE = "editable"


@dataclass(frozen=True, slots=True)
class Attrs:
    """What the backend says about one node. Every `str` field is either a label the policy
    engine reads or listed in `NON_LABEL_FIELDS` (`labels.py`); a test pins that split.

    Absent evidence is the empty string or None, never a guess: API 24 has no `hint`, and a
    backend without drawing order leaves `drawing_order` None.
    """

    class_name: str
    package: str
    resource_id: str
    text: str
    content_desc: str
    hint: str
    bounds: Rect
    flags: frozenset[Flag]
    drawing_order: int | None
    native_id: str | None


@dataclass(frozen=True, slots=True)
class NodeSpec:
    attrs: Attrs
    children: tuple[NodeSpec, ...]


class WindowKind(Enum):
    """AccessibilityWindowInfo types. A backend that cannot read the type reports UNKNOWN."""

    APPLICATION = "application"
    INPUT_METHOD = "input_method"
    SYSTEM = "system"
    OVERLAY = "overlay"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class WindowSpec:
    """`active` is the window with input focus. `layer` is the z-order when the backend knows
    it (higher is on top), else None."""

    package: Package
    kind: WindowKind
    bounds: Rect
    active: bool
    layer: int | None
    root: NodeSpec


@dataclass(frozen=True, slots=True)
class Node:
    id: NodeId
    window: WindowId
    parent: NodeId | None
    end: NodeId
    depth: int
    children: tuple[NodeId, ...]
    attrs: Attrs

    def has(self, flag: Flag) -> bool:
        return flag in self.attrs.flags


@dataclass(frozen=True, slots=True)
class Window:
    id: WindowId
    package: Package
    kind: WindowKind
    bounds: Rect
    active: bool
    layer: int | None
    root: NodeId


@dataclass(frozen=True, slots=True)
class Screen:
    """Invariants: `nodes[i].id == i`; at most one window is active; every node's subtree lies
    inside its window's id range; `rotation` and `display` describe the same read."""

    display: Size
    rotation: Rotation
    windows: tuple[Window, ...]
    nodes: tuple[Node, ...]
    toasts: tuple[str, ...]

    @staticmethod
    def build(
        display: Size, rotation: Rotation, windows: Sequence[WindowSpec], toasts: Sequence[str] = ()
    ) -> Screen:
        if sum(spec.active for spec in windows) > 1:
            raise Refusal(ErrorCode.INTERNAL, "The backend reported more than one active window.")
        nodes: list[Node] = []

        def walk(spec: NodeSpec, window: WindowId, parent: NodeId | None, depth: int) -> NodeId:
            id = NodeId(len(nodes))
            nodes.append(Node(id, window, parent, id, depth, (), spec.attrs))
            children = tuple(walk(child, window, id, depth + 1) for child in spec.children)
            nodes[id] = replace(nodes[id], end=NodeId(len(nodes)), children=children)
            return id

        built = []
        for i, spec in enumerate(windows):
            root = walk(spec.root, WindowId(i), None, 0)
            built.append(
                Window(WindowId(i), spec.package, spec.kind, spec.bounds, spec.active, spec.layer, root)
            )
        return Screen(display, rotation, tuple(built), tuple(nodes), tuple(toasts))

    def node(self, id: NodeId) -> Node:
        return self.nodes[id]

    def subtree(self, id: NodeId) -> Sequence[Node]:
        return self.nodes[id : self.nodes[id].end]

    def ancestors(self, id: NodeId) -> Iterator[Node]:
        """Nearest first, the node itself excluded."""
        parent = self.nodes[id].parent
        while parent is not None:
            yield self.nodes[parent]
            parent = self.nodes[parent].parent

    def window_of(self, id: NodeId) -> Window:
        return self.windows[self.nodes[id].window]

    def active_window(self) -> Window | None:
        return next((w for w in self.windows if w.active), None)

    def windows_at(self, p: Point) -> tuple[Window, ...]:
        return tuple(w for w in self.windows if w.bounds.contains(p))
