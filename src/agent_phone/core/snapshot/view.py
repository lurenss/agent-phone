"""Which nodes a snapshot shows, which get refs, and what each line says.

Compact keeps every actionable node and every node with visible text that no actionable node
already owns (A4-1). A label folds into the actionable node whose surface holds it, so a
button whose words sit in a child prints once. Containers with no name and no ref
disappear and their children move up one level. A text line that only repeats the line it
sits under is dropped. A nameless consumer whose only consumer descendant takes a tap at its
center is a wrapper and folds into that descendant: the system UI wraps each quick-settings
tile this way, 6 px larger on each side, which gave 10 of the 31 refs in the shade fixture
before folding.

Skeleton keeps collections, named groups and actionable nodes outside collections, and prints a
row count on each collection: the rows that hold at least one line. The agent drills into one
with `snapshot --root <ref>`. A pager or list that holds one row is a page, not a choice of
rows, so the skeleton looks through it and folds the first collection that has several rows.

Ref numbers are the pre-order ordinal of the node among the ref-eligible nodes of the whole
surface window, not of the lines printed. The same element on an unchanged screen therefore
keeps its number across a full snapshot, a skeleton and a drill-down.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from enum import Enum

from agent_phone.core.geometry import Rect
from agent_phone.core.labels import shown_nodes, shown_values
from agent_phone.core.role import (
    COLLECTIONS,
    VALUE_ROLES,
    Role,
    consumes_touch,
    is_actionable,
    role_of,
    shows_surface,
)
from agent_phone.core.screen import Flag, Node, NodeId, Screen, Window
from agent_phone.core.snapshot.surface import Pick, Surface


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
    LOSSY = "lossy"


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


DETAIL_CHARS = 40

STATE_FLAGS: Mapping[Flag, State] = {
    Flag.CHECKED: State.CHECKED,
    Flag.SELECTED: State.SELECTED,
    Flag.FOCUSED: State.FOCUSED,
    Flag.PASSWORD: State.SECRET,
}


def ref_numbers(surface: Surface) -> Mapping[NodeId, int]:
    """Pre-order ordinal among ref-eligible nodes of the surface window: actionable
    (`role.is_actionable`) and not a wrapper that folds into the one consumer inside it."""
    screen = surface.screen
    numbers: dict[NodeId, int] = {}
    for window in surface.windows:
        for node in screen.subtree(window.root):
            if is_actionable(node.attrs, role_of(node.attrs)) and not is_wrapper(screen, node):
                numbers[node.id] = len(numbers) + 1
    return numbers


def is_wrapper(screen: Screen, node: Node) -> bool:
    """A nameless consumer whose only consumer descendant is actionable and contains its
    center. A tap on the wrapper's center reaches that descendant, so one ref covers both."""
    if not consumes_touch(node.attrs) or shown_values(screen, node, role_of(node.attrs)):
        return False
    inner = [m for m in screen.subtree(node.id)[1:] if consumes_touch(m.attrs)]
    return (
        len(inner) == 1
        and is_actionable(inner[0].attrs, role_of(inner[0].attrs))
        and inner[0].attrs.bounds.contains(node.attrs.bounds.center())
    )


def build_view(surface: Surface, mode: Mode) -> View:
    numbers = ref_numbers(surface)
    entries = full_entries(surface, numbers) if mode is Mode.FULL else compact_entries(surface, numbers)
    screen = surface.screen
    nodes = tuple(node for _, node in entries)
    lines = tuple(
        replace(line, rows=len(row_groups(screen, nodes, i))) if line.role in COLLECTIONS else line
        for i, (line, _) in enumerate(entries)
    )
    view = View(surface, mode, lines, nodes, refs_of(lines, nodes))
    return skeleton(view) if mode is Mode.SKELETON else view


def compact_entries(surface: Surface, numbers: Mapping[NodeId, int]) -> list[tuple[Line, NodeId]]:
    screen = surface.screen
    entries: list[tuple[Line, NodeId]] = []

    def visit(id: NodeId, depth: int, owned: bool, parent_name: str) -> None:
        node = screen.node(id)
        role = role_of(node.attrs)
        consumer = consumes_touch(node.attrs)
        below = (depth, owned, parent_name)
        if id in numbers:
            line = line_of(screen, node, role, depth, numbers[id])
            entries.append((line, id))
            below = (depth + 1, shows_surface(node.attrs, role) or (owned and not consumer), line.name)
        elif consumer:
            below = (depth, False, parent_name)
        elif not owned and Flag.VISIBLE in node.attrs.flags:
            line = line_of(screen, node, role, depth, None)
            if line.name and (line.name, line.detail) != (parent_name, ""):
                entries.append((line, id))
                below = (depth + 1, False, line.name)
        for child in node.children:
            visit(child, *below)

    if surface.pick is Pick.ALL:
        for window in surface.windows:
            entries.append((window_line(window), window.root))
            visit(window.root, 1, False, "")
    else:
        visit(surface.root, 0, False, "")
    return entries


def full_entries(surface: Surface, numbers: Mapping[NodeId, int]) -> list[tuple[Line, NodeId]]:
    screen = surface.screen
    entries: list[tuple[Line, NodeId]] = []
    for root in surface.roots:
        top = screen.node(root).depth
        if surface.pick is Pick.ALL:
            entries.append((window_line(screen.window_of(root)), root))
            top -= 1
        entries.extend(
            (line_of(screen, node, role_of(node.attrs), node.depth - top, numbers.get(node.id)), node.id)
            for node in screen.subtree(root)
        )
    return entries


def window_line(window: Window) -> Line:
    """The line that opens a window's part of an all-windows tree: its package, its kind as the
    detail, `focused` on the active window, and its bounds."""
    return Line(
        ref=None,
        depth=0,
        role=Role.GROUP,
        name=window.package,
        detail=window.kind.value,
        value="",
        id_hint="",
        states=frozenset({State.FOCUSED} if window.active else ()),
        bounds=window.bounds,
        rows=None,
        folded=0,
    )


def states_of(screen: Screen, node: Node, role: Role) -> frozenset[State]:
    """LOSSY when any node whose labels the line shows is LOSSY, such as the child that names a
    button."""
    attrs = node.attrs
    states = {state for flag, state in STATE_FLAGS.items() if flag in attrs.flags}
    if Flag.ENABLED not in attrs.flags:
        states.add(State.DISABLED)
    if Flag.VISIBLE not in attrs.flags:
        states.add(State.OFFSCREEN)
    if any(member.has(Flag.LOSSY) for member in shown_nodes(screen, node, role)):
        states.add(State.LOSSY)
    return frozenset(states)


def line_of(screen: Screen, node: Node, role: Role, depth: int, ref: int | None) -> Line:
    attrs = node.attrs
    shown = shown_values(screen, node, role)
    name = shown[0] if shown else ""
    detail = ", ".join(shown[1:])
    if len(detail) > DETAIL_CHARS:
        detail = detail[:DETAIL_CHARS] + "…"
    secret = Flag.PASSWORD in attrs.flags
    return Line(
        ref=ref,
        depth=depth,
        role=role,
        name=name,
        detail=detail,
        value=attrs.text if role in VALUE_ROLES and not secret else "",
        id_hint="" if name else attrs.resource_id.rpartition("/")[2],
        states=states_of(screen, node, role),
        bounds=attrs.bounds,
        rows=None,
        folded=0,
    )


PAGE_ROLES = frozenset({Role.PAGER, Role.LIST})


def folds(line: Line) -> bool:
    """A collection with a ref: skeleton and budget fitting may hide its rows, because the
    agent can drill into it with `snapshot --root`."""
    return line.ref is not None and line.role in COLLECTIONS


def is_page(line: Line) -> bool:
    """A pager or list with one row. It selects nothing, and hiding its row hides the whole
    screen (the Instagram feed has a pager over a list over the feed list, A4-1). A scroll
    view never counts: it holds one child by construction."""
    return folds(line) and line.role in PAGE_ROLES and line.rows == 1


def row_groups(screen: Screen, nodes: Sequence[NodeId], i: int) -> list[list[int]]:
    """Indexes of the lines under line `i`, grouped by the child of its node that holds them.
    Lines are in pre-order, so the lines under `i` are the run after it inside its subtree."""
    collection = screen.node(nodes[i])
    groups: list[list[int]] = []
    row_end = -1
    for j in range(i + 1, len(nodes)):
        if nodes[j] >= collection.end:
            break
        if nodes[j] >= row_end:
            row = next(
                n for n in (screen.node(nodes[j]), *screen.ancestors(nodes[j])) if n.parent == collection.id
            )
            row_end = row.end
            groups.append([])
        groups[-1].append(j)
    return groups


def skeleton(view: View, through_pages: bool = True) -> View:
    """Hide every line under a folding collection, counting them on its line. Pages stay open
    unless `through_pages` is False, which budget fitting uses when nothing else made it fit."""
    screen = view.surface.screen
    lines: list[Line] = []
    nodes: list[NodeId] = []
    open_end = -1
    for line, node in zip(view.lines, view.nodes, strict=True):
        if node < open_end:
            lines[-1] = replace(lines[-1], folded=lines[-1].folded + 1)
            continue
        lines.append(line)
        nodes.append(node)
        open_end = screen.node(node).end if folds(line) and not (through_pages and is_page(line)) else -1
    return View(view.surface, Mode.SKELETON, tuple(lines), tuple(nodes), refs_of(lines, nodes))


def is_window_line(surface: Surface, line: Line) -> bool:
    """True for the line that opens a window in an all-windows tree. Every other line of that
    tree is indented under one, so the lines at depth 0 are exactly the window lines."""
    return surface.pick is Pick.ALL and line.depth == 0


def pick_lines(view: View, indexes: Sequence[int]) -> View:
    """The lines at `indexes`, flat, as a view of their own. Refs keep their numbers."""
    lines = tuple(replace(view.lines[i], depth=0) for i in indexes)
    nodes = tuple(view.nodes[i] for i in indexes)
    return View(view.surface, view.mode, lines, nodes, refs_of(lines, nodes))


def refs_of(lines: Sequence[Line], nodes: Sequence[NodeId]) -> Mapping[int, NodeId]:
    return {line.ref: node for line, node in zip(lines, nodes, strict=True) if line.ref is not None}
