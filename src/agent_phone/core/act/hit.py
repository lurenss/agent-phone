"""Where a touch will land, and which node will take it.

A coordinate tap goes to whatever is at the point (`UiObject.click` injects at the center,
`_selector.py:138`), so the policy engine must judge the node at the point, not the node the
caller meant. This module makes those the same node, or refuses:

1. The target's window must be the active one, and no other window may cover the point. The
   keyboard, a status bar strip, an overlay and any window whose stacking is unknown all
   block. A non-active application window that covers the whole display counts as below,
   because a full-screen window above the active one would have the focus.
2. Inside the window, dispatch follows Android's: children containing the point in reverse
   drawing order, deepest consumer first. Equal or missing drawing order between two
   branches that both hold a consumer is ambiguous, and an ambiguous point is never used.
3. `plan_point` tries the visible center, then the four quadrant centers, and returns the
   first point whose receiver is exactly the target.
"""

from __future__ import annotations

from dataclasses import dataclass

from agent_phone.core.geometry import Point
from agent_phone.core.labels import Label
from agent_phone.core.screen import Node, NodeId, Screen, Window


@dataclass(frozen=True, slots=True)
class Ambiguous:
    candidates: tuple[NodeId, ...]


def covering_window(screen: Screen, target: Window, point: Point) -> Window | None:
    raise NotImplementedError


def receiver_at(screen: Screen, window: Window, point: Point) -> NodeId | Ambiguous | None:
    raise NotImplementedError


def plan_point(screen: Screen, node: Node) -> Point:
    """Raises `Refusal(OCCLUDED)` naming the covering window or node, or
    `Refusal(NOT_ACTIONABLE)` when the node has no visible area."""
    raise NotImplementedError


def context_labels(screen: Screen, node: Node) -> tuple[Label, ...]:
    """The engine's `Site.context`: the labels of the node's whole window minus its own surface."""
    raise NotImplementedError
