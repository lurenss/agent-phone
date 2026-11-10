"""What one snapshot shows that another did not, and what it no longer shows.

A line is the same line when everything it prints but its ref, its indent and its bounds is equal.
A ref number and a place change when lines above are added or the list scrolls, and neither says
that the element changed. Two equal lines count twice, so a second "Edit" button is an added line.
Lines that also kept their place are paired first, so of two equal lines the one that stayed is
the kept one and the one at a new place is the added one.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace

from agent_phone.core.snapshot.budget import render_line
from agent_phone.core.snapshot.snapshot import Snapshot
from agent_phone.core.snapshot.view import Line


@dataclass(frozen=True, slots=True)
class Diff:
    """`added` are lines of the later snapshot as it prints them, refs included, without indent.
    `gone` are lines of the earlier one with no ref and no bounds, because neither can be used."""

    kept: int
    added: tuple[str, ...]
    gone: tuple[str, ...]


def diff(before: Snapshot, after: Snapshot) -> Diff:
    stayed, old, new = _pair(before.lines, after.lines, _placed)
    moved, gone, added = _pair(old, new, _same)
    return Diff(
        kept=stayed + moved,
        added=tuple(render_line(replace(line, depth=0), after.id) for line in added),
        gone=tuple(render_line(_same(line), before.id) for line in gone),
    )


def _placed(line: Line) -> Line:
    return replace(line, ref=None, depth=0)


def _same(line: Line) -> Line:
    return replace(line, ref=None, depth=0, bounds=None)


def _pair(
    old: Sequence[Line], new: Sequence[Line], key: Callable[[Line], Line]
) -> tuple[int, list[Line], list[Line]]:
    """How many lines pair up under `key`, then the lines of each side that found no pair, in order."""
    shared = Counter(map(key, old)) & Counter(map(key, new))
    return shared.total(), _rest(old, shared, key), _rest(new, shared, key)


def _rest(lines: Sequence[Line], shared: Counter[Line], key: Callable[[Line], Line]) -> list[Line]:
    left = Counter(shared)
    rest = []
    for line in lines:
        if left[key(line)]:
            left[key(line)] -= 1
        else:
            rest.append(line)
    return rest
