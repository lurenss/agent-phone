"""Which nodes a snapshot shows, which get refs, and what each line says.

Compact keeps every actionable node and every node with visible text that no actionable node
already owns (A4-1). A label folds into the actionable node whose surface holds it, so a
button whose words sit in a child prints once. Containers with no name and no ref
disappear and their children move up one level. A nameless consumer whose only consumer
descendant covers it is a wrapper and folds into that descendant: the system UI wraps each
quick-settings tile this way, which gave 10 of the 31 refs in the shade fixture before folding.

Skeleton keeps collections, named groups and actionable nodes outside collections, and prints a
row count on each collection. The agent drills into one with `snapshot --root <ref>`.

Ref numbers are the pre-order ordinal of the node among the ref-eligible nodes of the whole
surface window, not of the lines printed. The same element on an unchanged screen therefore
keeps its number across a full snapshot, a skeleton and a drill-down.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum

from agent_phone.core.geometry import Rect
from agent_phone.core.role import Role
from agent_phone.core.screen import NodeId
from agent_phone.core.snapshot.surface import Surface


class Mode(Enum):
    COMPACT = "compact"
    SKELETON = "skeleton"
    FULL = "full"


class State(Enum):
    DISABLED = "disabled"
    CHECKED = "checked"
    SELECTED = "selected"
    FOCUSED = "focused"
    SECRET = "secret"
    OFFSCREEN = "offscreen"


@dataclass(frozen=True, slots=True)
class Line:
    """One printed line. Persistable: it holds no NodeId, so a snapshot record outlives its Screen.

    `value` is a field's typed text, shown but never part of identity, and blank for SECRET.
    `rows` is set on collections, `folded` counts lines hidden under this one by skeleton or
    budget fitting.
    """

    ref: int | None
    depth: int
    role: Role
    name: str
    detail: str
    value: str
    id_hint: str
    states: frozenset[State]
    bounds: Rect | None
    rows: int | None
    folded: int


@dataclass(frozen=True, slots=True)
class View:
    """`nodes[i]` is the node behind `lines[i]`. `refs` maps each printed ref to its node."""

    surface: Surface
    mode: Mode
    lines: tuple[Line, ...]
    nodes: tuple[NodeId, ...]
    refs: Mapping[int, NodeId]


def ref_numbers(surface: Surface) -> Mapping[NodeId, int]:
    """Pre-order ordinal among ref-eligible nodes (`role.is_actionable`) of the surface window."""
    raise NotImplementedError


def build_view(surface: Surface, mode: Mode) -> View:
    # TODO: one pre-order walk from surface.root, skipping nodes without VISIBLE:
    #   eligible = is_actionable(attrs, role)  -> line with ref ref_numbers[node]
    #   owned    = node lies in the surface of an eligible ancestor -> no line, it is that
    #              line's name or detail
    #   text     = has a naming label and is not owned -> line without ref
    #   else     = no line; children are hoisted to this depth
    #   SKELETON: below a collection, print only the collection line with rows=len(children)
    #   FULL: every node gets a line
    raise NotImplementedError
