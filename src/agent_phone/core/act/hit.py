"""Where a touch will land, and which node will take it.

A coordinate tap goes to whatever is at the point. The server's `click(x, y)` is a touch down,
100 ms, and a touch up at that point (A2-11), so the policy engine must judge the node at the
point, not the node the caller meant. This module makes those the same node, or refuses:

1. The target's window must be the active one, and no other window may cover the point. The
   keyboard, a status bar strip, an overlay and any window whose stacking is unknown all
   block. A dialog over an app needs no rule of its own: the dump of a dialog leaves the app
   beneath it out (A2-7).
2. Inside the window, dispatch follows Android's: children containing the point in reverse
   drawing order, deepest node that takes a touch first (`role.takes_touch`). Equal or missing
   drawing order between two branches that both hold one is ambiguous, and an ambiguous point
   is never used.
3. `plan_point` tries the visible center, then the four quadrant centers, and returns the
   first point whose receiver is exactly the target.
"""

from __future__ import annotations

from dataclasses import dataclass

from agent_phone.core.act.intent import Direction
from agent_phone.core.geometry import Point, Rect
from agent_phone.core.labels import Label, own_labels, owned
from agent_phone.core.outcome import ErrorCode, Refusal
from agent_phone.core.phone import Swipe
from agent_phone.core.role import COLLECTIONS, Role, role_of, simple_name, takes_touch
from agent_phone.core.screen import Node, NodeId, Screen, Window

SWIPE_SPAN = 0.6
SWIPE_MS = 275
"""As long as uiautomator2's own scroll (55 steps of about 5 ms), so the list scrolls and does not fling."""


@dataclass(frozen=True, slots=True)
class Ambiguous:
    candidates: tuple[NodeId, ...]


Receiver = NodeId | Ambiguous | None


def covering_window(screen: Screen, target: Window, point: Point) -> Window | None:
    """Any other window at the point covers it, unless the backend knows both layers and the
    other one is lower. A window without focus can still lie above and take the touch, such as a
    full-screen overlay that does not take focus."""
    for window in screen.windows_at(point):
        if window.id == target.id:
            continue
        if target.layer is not None and window.layer is not None and window.layer < target.layer:
            continue
        return window
    return None


def receiver_at(screen: Screen, window: Window, point: Point) -> Receiver:
    return receiver_in(screen, screen.node(window.root), point)


def receiver_in(screen: Screen, node: Node, point: Point) -> Receiver:
    """A node the dump marks not visible to the user still takes a touch inside its bounds: a view
    at alpha 0, such as a sheet that fades in, is not visible to the user and still takes touches."""
    if not node.attrs.bounds.contains(point):
        return None
    taking: list[tuple[Node, NodeId | Ambiguous]] = []
    for child in node.children:
        found = receiver_in(screen, screen.node(child), point)
        if found is not None:
            taking.append((screen.node(child), found))
    if len(taking) == 1:
        return taking[0][1]
    if taking:
        orders = [child.attrs.drawing_order for child, _ in taking]
        if None in orders or len(set(orders)) < len(orders):
            return Ambiguous(tuple(child.id for child, _ in taking))
        return max(taking, key=lambda pair: pair[0].attrs.drawing_order or 0)[1]
    return node.id if takes_touch(node.attrs) else None


def visible_area(screen: Screen, node: Node) -> Rect:
    display = Rect(0, 0, screen.display.width, screen.display.height)
    return node.attrs.bounds.intersect(screen.window_of(node.id).bounds).intersect(display)


def candidates(area: Rect) -> tuple[Point, ...]:
    width, height = area.right - area.left, area.bottom - area.top
    quarters = [(1, 1), (3, 1), (1, 3), (3, 3)]
    return (
        area.center(),
        *(Point(area.left + width * x // 4, area.top + height * y // 4) for x, y in quarters),
    )


def plan_point(screen: Screen, node: Node) -> Point:
    """Raises `Refusal(OCCLUDED)` naming the covering window or node, or
    `Refusal(NOT_ACTIONABLE)` when the node has no visible area."""
    window = screen.window_of(node.id)
    area = visible_area(screen, node)
    if area.empty:
        raise Refusal(
            ErrorCode.NOT_ACTIONABLE, "The element has no visible area to touch.", {"reason": "no_area"}
        )
    require_active(window)
    blocked: list[str] = []
    for point in candidates(area):
        cover = covering_window(screen, window, point)
        if cover is not None:
            blocked.append(f"window {cover.id} {cover.package} ({cover.kind.value})")
            continue
        found = receiver_at(screen, window, point)
        if found == node.id:
            return point
        blocked.append(describe(screen, found))
    raise Refusal(
        ErrorCode.OCCLUDED,
        "No point of the element would reach it: "
        f"{'; '.join(dict.fromkeys(blocked))} would take the touch. Take a new snapshot and look.",
        {"blocked_by": list(dict.fromkeys(blocked))},
    )


def require_active(window: Window) -> None:
    if not window.active:
        raise Refusal(
            ErrorCode.OCCLUDED,
            f"The element is in window {window.id} ({window.package}), which does not have input focus.",
            {"window": window.id},
        )


def describe(screen: Screen, found: Receiver) -> str:
    match found:
        case None:
            return "nothing that takes a tap"
        case Ambiguous(candidates=ids):
            return f"one of {len(ids)} overlapping elements whose order is unknown"
        case _:
            attrs = screen.node(found).attrs
            name = attrs.text or attrs.content_desc or attrs.resource_id or attrs.class_name
            return f"another element ({name!r})"


def row_labels(screen: Screen, node: Node) -> tuple[Label, ...]:
    """The words of the row a toggle sits in, outside the toggle itself. A switch often says only
    "On" or "Off", and its row says what it turns on. The row is the nearest ancestor that takes
    a touch, else the child of the nearest collection that holds the toggle, else its parent."""
    child = node
    for ancestor in screen.ancestors(node.id):
        if takes_touch(ancestor.attrs):
            return labels_outside(screen, ancestor, node)
        if role_of(ancestor.attrs) in COLLECTIONS:
            return labels_outside(screen, child, node)
        child = ancestor
    return () if node.parent is None else labels_outside(screen, screen.node(node.parent), node)


def labels_outside(screen: Screen, row: Node, node: Node) -> tuple[Label, ...]:
    return tuple(
        label
        for member in screen.subtree(row.id)
        if not node.id <= member.id < node.end
        for label in own_labels(member)
    )


def context_labels(screen: Screen, node: Node) -> tuple[Label, ...]:
    """The engine's `Site.context`: the labels of the node's whole window minus the labels of its
    own surface, which are the node and its descendants outside nested touch consumers."""
    return outside_labels(screen, screen.window_of(node.id), {member.id for member in owned(screen, node)})


def outside_labels(screen: Screen, window: Window, own: set[NodeId]) -> tuple[Label, ...]:
    """Every label of `window` except those of the nodes in `own`."""
    return tuple(
        label
        for member in screen.subtree(window.root)
        if member.id not in own
        for label in own_labels(member)
    )


def runs_across(screen: Screen, node: Node) -> bool:
    """A pager, a horizontal scroll view, or a collection with two rows side by side. A sideways
    swipe on a list that runs down lands on one row, and a row can act on a swipe: Samsung's
    Phone and Contacts call on one, and a notification is dismissed by one."""
    if role_of(node.attrs) is Role.PAGER or simple_name(node.attrs.class_name) == "HorizontalScrollView":
        return True
    rows = [b for child in node.children if not (b := screen.node(child).attrs.bounds).empty]
    pairs = zip(rows, rows[1:], strict=False)
    return any(a.left != b.left and a.top < b.bottom and b.top < a.bottom for a, b in pairs)


def swipe_across(screen: Screen, node: Node, direction: Direction) -> Swipe:
    """A swipe over SWIPE_SPAN of the collection's visible area. `Direction.DOWN` shows what is
    below, so the finger moves up. The swipe starts and ends inside the collection, under no
    other window, and its start lands on the collection or something inside it."""
    area = visible_area(screen, node)
    if area.empty:
        raise Refusal(ErrorCode.NOT_ACTIONABLE, "The element has no visible area.", {"reason": "no_area"})
    window = screen.window_of(node.id)
    require_active(window)
    middle = area.center()
    near, far = (1 - SWIPE_SPAN) / 2, (1 + SWIPE_SPAN) / 2
    height, width = area.bottom - area.top, area.right - area.left
    match direction:
        case Direction.DOWN:
            start, end = (
                Point(middle.x, area.top + int(height * far)),
                Point(middle.x, area.top + int(height * near)),
            )
        case Direction.UP:
            start, end = (
                Point(middle.x, area.top + int(height * near)),
                Point(middle.x, area.top + int(height * far)),
            )
        case Direction.RIGHT:
            start, end = (
                Point(area.left + int(width * far), middle.y),
                Point(area.left + int(width * near), middle.y),
            )
        case Direction.LEFT:
            start, end = (
                Point(area.left + int(width * near), middle.y),
                Point(area.left + int(width * far), middle.y),
            )
    taker = receiver_in(screen, screen.node(window.root), start)
    inside = taker is None or (isinstance(taker, int) and node.id <= taker < node.end)
    if not inside:
        raise Refusal(
            ErrorCode.OCCLUDED,
            "The swipe would start on an element outside the list.",
            {"point": [start.x, start.y]},
        )
    for point in (start, end):
        cover = covering_window(screen, window, point)
        if cover is not None:
            raise Refusal(
                ErrorCode.OCCLUDED,
                f"Window {cover.id} {cover.package} ({cover.kind.value}) covers the swipe.",
                {"point": [point.x, point.y]},
            )
    return Swipe(start, end, SWIPE_MS)
