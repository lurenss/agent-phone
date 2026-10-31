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
        raise NotImplementedError

    def center(self) -> Point:
        raise NotImplementedError

    def intersect(self, other: Rect) -> Rect:
        raise NotImplementedError

    def covers(self, other: Rect) -> bool:
        raise NotImplementedError
