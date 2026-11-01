"""Where a touch will land, and which node will take it.

A coordinate tap goes to whatever is at the point. The server's `click(x, y)` is a touch down,
100 ms, and a touch up at that point (A2-11), so the policy engine must judge the node at the
point, not the node the caller meant. This module makes those the same node, or refuses:

1. The target's window must be the active one, and no other window may cover the point. The
   keyboard, a status bar strip, an overlay and any window whose stacking is unknown all
   block. A non-active application window that covers the whole display counts as below,
   because a full-screen window above the active one would have the focus. A dialog over an
   app needs no rule of its own: the dump of a dialog leaves the app beneath it out (A2-7).
2. Inside the window, dispatch follows Android's: children containing the point in reverse
   drawing order, deepest consumer first. Equal or missing drawing order between two
   branches that both hold a consumer is ambiguous, and an ambiguous point is never used.
3. `plan_point` tries the visible center, then the four quadrant centers, and returns the
   first point whose receiver is exactly the target.
"""

from __future__ import annotations

from dataclasses import dataclass

from agent_phone.core.act.intent import Direction
from agent_phone.core.geometry import Point, Rect
from agent_phone.core.labels import Label, own_labels
from agent_phone.core.outcome import ErrorCode, Refusal
from agent_phone.core.phone import Swipe
from agent_phone.core.role import consumes_touch
from agent_phone.core.screen import Flag, Node, NodeId, Screen, Window, WindowKind

SWIPE_SPAN = 0.6
SWIPE_STEPS = 55
"""The steps uiautomator2 uses for a scroll, about 5 ms each, so the list scrolls and does not fling."""


@dataclass(frozen=True, slots=True)
class Ambiguous:
    candidates: tuple[NodeId, ...]


Receiver = NodeId | Ambiguous | None


def covering_window(screen: Screen, target: Window, point: Point) -> Window | None:
    display = Rect(0, 0, screen.display.width, screen.display.height)
    for window in screen.windows_at(point):
        if window.id == target.id:
            continue
        if target.layer is not None and window.layer is not None:
            if window.layer > target.layer:
                return window
            continue
        below = window.kind is WindowKind.APPLICATION and not window.active and window.bounds.covers(display)
        if not below:
            return window
    return None


def receiver_at(screen: Screen, window: Window, point: Point) -> Receiver:
    return receiver_in(screen, screen.node(window.root), point)


def receiver_in(screen: Screen, node: Node, point: Point) -> Receiver:
    if Flag.VISIBLE not in node.attrs.flags or not node.attrs.bounds.contains(point):
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
    return node.id if consumes_touch(node.attrs) else None


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


def context_labels(screen: Screen, node: Node) -> tuple[Label, ...]:
    """The engine's `Site.context`: the labels of the node's whole window minus the labels of its
    own surface, which are the node and its descendants outside nested touch consumers."""
    own: set[NodeId] = set()
    i = node.id
    while i < node.end:
        member = screen.nodes[i]
        if member.id != node.id and consumes_touch(member.attrs):
            i = member.end
            continue
        own.add(member.id)
        i += 1
    window = screen.window_of(node.id)
    return tuple(
        label
        for member in screen.subtree(window.root)
        if member.id not in own
        for label in own_labels(member)
    )


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
    return Swipe(start, end, SWIPE_STEPS)
