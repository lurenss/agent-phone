"""Which way a collection scrolls, read from what the dump shows of it.

A swipe along the axis a collection does not run lands on one of its items, and an item can act on
it: a recents card dismisses an app, a call-log row calls, a notification is dismissed. `act()`
refuses such a swipe (`refuse_wrong_axis`) and picks the path of the sideways swipe it sends
(`clear_height`).

The dump shows the children that are on screen. A layout manager keeps the next card attached
beyond the edge, and the dump clips it to an empty strip. So a collection runs across when any of
these holds, and a collection that none of them proves reads as a list that runs down:

- it is a pager or a horizontal scroll view, or its parent is a pager and it does not show two
  items one above the other (a call log in a pager page is a list that runs down);
- a child is clipped to an empty strip at its left or right edge, level with one that shows;
- two children that show sit side by side;
- its one child that shows has space on both sides, spans at most 90 % of the width and fills at
  least 75 % of the height: one card of a row.

Known limit: a sideways collection that attaches one child that fills it, and shows no other sign,
reads as a list that runs down. Nothing in the dump tells its page from a page of a vertical feed.
"""

from __future__ import annotations

from typing import NoReturn

from agent_phone.core.act.intent import Direction
from agent_phone.core.geometry import Rect
from agent_phone.core.outcome import ErrorCode, Refusal
from agent_phone.core.role import Role, role_of, simple_name
from agent_phone.core.screen import Flag, Node, Screen

SWIPE_SPAN = 0.6
ONE_CARD_MOST_OF_THE_WIDTH = 90
ONE_CARD_LEAST_OF_THE_HEIGHT = 75
CLEAR_MARGIN = 8
"""A dump's bounds can be a pixel off, so a sideways swipe keeps this far from a row it avoids."""


def span(start: int, length: int) -> tuple[int, int]:
    """The two ends of a swipe over SWIPE_SPAN of `length`, centered in it."""
    near, far = (1 - SWIPE_SPAN) / 2, (1 + SWIPE_SPAN) / 2
    return start + int(length * near), start + int(length * far)


def level(a: Rect, b: Rect) -> bool:
    return a.top < b.bottom and b.top < a.bottom


def children_on(screen: Screen, node: Node, area: Rect) -> tuple[list[Rect], list[Rect]]:
    """The children that show, clipped to `area`, and the ones clipped away at its left or right edge."""
    shown, away = [], []
    for child in node.children:
        box = screen.node(child).attrs.bounds
        if not (clipped := box.intersect(area)).empty:
            shown.append(clipped)
        elif box.left >= area.right or box.right <= area.left:
            away.append(box)
    return shown, away


def runs_across(screen: Screen, node: Node, area: Rect) -> bool:
    if role_of(node.attrs) is Role.PAGER or simple_name(node.attrs.class_name) == "HorizontalScrollView":
        return True
    shown, away = children_on(screen, node, area)
    return (
        any(level(strip, item) for strip in away for item in shown)
        or any(a.left != b.left and level(a, b) for a, b in zip(shown, shown[1:], strict=False))
        or is_one_card(shown, area)
        or (in_pager(screen, node) and not is_stacked(shown))
    )


def in_pager(screen: Screen, node: Node) -> bool:
    return node.parent is not None and role_of(screen.node(node.parent).attrs) is Role.PAGER


def is_stacked(shown: list[Rect]) -> bool:
    """An item entirely below another."""
    return bool(shown) and max(r.top for r in shown) >= min(r.bottom for r in shown)


def is_one_card(shown: list[Rect], area: Rect) -> bool:
    if len(shown) != 1:
        return False
    card = shown[0]
    width, height = card.right - card.left, card.bottom - card.top
    return (
        area.left < card.left
        and card.right < area.right
        and width * 100 <= (area.right - area.left) * ONE_CARD_MOST_OF_THE_WIDTH
        and height * 100 >= (area.bottom - area.top) * ONE_CARD_LEAST_OF_THE_HEIGHT
    )


def is_grid(screen: Screen, node: Node, area: Rect) -> bool:
    """At least two rows that each hold at least two items side by side. A lone item below
    side-by-side items, such as a footer or a page indicator, is no row of a grid."""
    shown, _ = children_on(screen, node, area)
    return sum(len(row) >= 2 for row in rows_of(shown)) >= 2


def rows_of(items: list[Rect]) -> list[list[Rect]]:
    """Items top to bottom, a new row when one starts below the earliest end of the row so far, so
    that the tiles of a staggered grid still fall into rows."""
    rows: list[list[Rect]] = []
    ends = 0
    for item in sorted(items, key=lambda r: (r.top, r.left)):
        if rows and item.top < ends:
            rows[-1].append(item)
            ends = min(ends, item.bottom)
        else:
            rows.append([item])
            ends = item.bottom
    return rows


def refuse_wrong_axis(screen: Screen, node: Node, direction: Direction, area: Rect) -> None:
    """Raises `Refusal(NOT_ACTIONABLE)` with reason `wrong_axis` for a swipe that would land on an item
    that can act on it. A node with no visible area is left to the swipe's own refusal."""
    if area.empty:
        return
    across = runs_across(screen, node, area)
    match direction:
        case Direction.LEFT | Direction.RIGHT if not across:
            refuse("The list runs down, so a sideways swipe would land on one row. Scroll up or down.")
        case Direction.LEFT | Direction.RIGHT:
            clear_height(screen, node, area)
        case Direction.UP | Direction.DOWN if across and not is_grid(screen, node, area):
            refuse(
                "The items run side by side, so an up or down swipe would land on one card, and a card "
                "can dismiss on a swipe. Scroll left or right."
            )


def refuse(message: str) -> NoReturn:
    raise Refusal(ErrorCode.NOT_ACTIONABLE, message, {"reason": "wrong_axis"})


def lists_that_run_down(screen: Screen, node: Node, area: Rect) -> list[tuple[Node, Rect]]:
    """The scrolling views inside `node` that run down, each with the part of it that shows."""
    found = []
    for inner in screen.subtree(node.id)[1:]:
        shown = inner.attrs.bounds.intersect(area)
        if inner.has(Flag.SCROLLABLE) and not shown.empty and not runs_across(screen, inner, shown):
            found.append((inner, shown))
    return found


def clear_height(screen: Screen, node: Node, area: Rect) -> int:
    """The height of a sideways swipe across `node` that crosses no row of a list that runs down
    inside it: the middle when that is clear, else the nearest band between rows that is clear.
    Raises `Refusal(NOT_ACTIONABLE)` with reason `wrong_axis` when the rows leave no such band."""
    near, far = span(area.left, area.right - area.left)
    middle = area.center().y
    rows = sorted(
        (row.top, row.bottom)
        for inner, shown in lists_that_run_down(screen, node, area)
        for child in inner.children
        if not (row := screen.node(child).attrs.bounds.intersect(shown)).empty
        and row.left < far
        and near < row.right
    )
    if not rows:
        return middle
    bands, cursor = [], area.top
    for top, bottom in rows:
        if top > cursor:
            bands.append((cursor, top))
        cursor = max(cursor, bottom)
    if cursor < area.bottom:
        bands.append((cursor, area.bottom))
    roomy = [(top, bottom) for top, bottom in bands if bottom - top > 2 * CLEAR_MARGIN]
    if not roomy:
        refuse(
            "Every sideways swipe over this collection would start on a row of a list inside it that "
            "runs down, and a row can act on a swipe. Tap the tab or button that switches the page instead."
        )
    top, bottom = min(
        roomy, key=lambda band: 0 if band[0] <= middle < band[1] else min(abs(middle - b) for b in band)
    )
    return min(max(middle, top + CLEAR_MARGIN), bottom - 1 - CLEAR_MARGIN)
