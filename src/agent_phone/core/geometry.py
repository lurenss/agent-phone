"""Screen geometry in physical pixels of the current rotation, origin top-left, as the dump reports it."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


@dataclass(frozen=True, slots=True)
class Point:
    x: int
    y: int


@dataclass(frozen=True, slots=True)
class Size:
    width: int
    height: int


STRIP_FRACTION = 0.08
"""The most a status or navigation bar takes of the display across its thin side. The J7's status
bar takes 3.3%, a three-button navigation bar is about 7.5%, and the Thor's status bar is 5.1%."""


class Rotation(Enum):
    """Surface.ROTATION_* as the dump's `rotation` attribute reports it."""

    NATURAL = 0
    LEFT = 1
    UPSIDE_DOWN = 2
    RIGHT = 3


@dataclass(frozen=True, slots=True)
class Rect:
    """Half-open: x in [left, right), y in [top, bottom). An empty rect contains no point.

    Bounds from the dump are already clipped to the visible part of the node, so a row half
    under the bottom bar has the clipped rect, not its layout rect.
    """

    left: int
    top: int
    right: int
    bottom: int

    @property
    def empty(self) -> bool:
        return self.right <= self.left or self.bottom <= self.top

    def contains(self, p: Point) -> bool:
        return self.left <= p.x < self.right and self.top <= p.y < self.bottom

    def center(self) -> Point:
        return Point((self.left + self.right) // 2, (self.top + self.bottom) // 2)

    def intersect(self, other: Rect) -> Rect:
        return Rect(
            max(self.left, other.left),
            max(self.top, other.top),
            min(self.right, other.right),
            min(self.bottom, other.bottom),
        )

    def fills(self, display: Size) -> bool:
        """True when none of the four edges is inset from the display's edge by more than a bar's
        thickness (`STRIP_FRACTION` of the display's length along that axis). A full-screen app
        qualifies without covering the display exactly: the bars can lie outside its window (a J7 app
        at `[0,63][1080,1794]`), a backend can report bounds a pixel inside the display, and an app can
        start below a thin strip (YouTube at `[0,25][1920,1080]`).

        The limit is that a dialog whose margins are all under 8% fills the display by this rule, so
        `dialog` is false for it and `--surface dialog` does not find it. The J7's Bluetooth dialog
        is inset 1530 px from the top (A2-7), far over the limit."""
        across, down = STRIP_FRACTION * display.width, STRIP_FRACTION * display.height
        return (
            self.left <= across
            and self.top <= down
            and display.width - self.right <= across
            and display.height - self.bottom <= down
        )
