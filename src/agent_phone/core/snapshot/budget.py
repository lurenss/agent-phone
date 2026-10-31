"""The 8 KB output budget (A4-1) and the text form of a snapshot line.

Fitting degrades in a fixed order, and each step only removes: details, then bounds on non-ref
lines, then rows beyond the first k of each collection (k halves until it fits, each cut
collection keeps its ref and a `folded` count so the agent can drill), then a skeleton that
folds pages too. The
snapshot reports `truncated` and how many lines were cut, never a silently short tree.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterator
from dataclasses import replace

from agent_phone.core.snapshot.snapshot import SnapshotId
from agent_phone.core.snapshot.view import Line, State, View, folds, refs_of, row_groups, skeleton

BUDGET_BYTES = 8 * 1024
ENVELOPE_RESERVE = 512


def render_line(line: Line, snapshot: SnapshotId) -> str:
    """`  @k3x9q:e4 button "<name>" "<detail>" [631,448,1038,564]`

    Indent two spaces per depth. Ref first so an agent can copy it, role, quoted name, then
    quoted detail, `value=`, `#id` when the name is empty, states, `(N rows)`, `(+N)` for
    folded lines, and bounds last.
    """
    parts = [] if line.ref is None else [f"@{snapshot}:e{line.ref}"]
    parts.append(line.role.value)
    if line.name:
        parts.append(quoted(line.name))
    if line.detail:
        parts.append(quoted(line.detail))
    if line.value:
        parts.append(f"value={quoted(line.value)}")
    if line.id_hint:
        parts.append(f"#{line.id_hint}")
    parts.extend(state.value for state in State if state in line.states)
    if line.rows is not None:
        parts.append(f"({line.rows} row)" if line.rows == 1 else f"({line.rows} rows)")
    if line.folded:
        parts.append(f"(+{line.folded})")
    if line.bounds is not None:
        b = line.bounds
        parts.append(f"[{b.left},{b.top},{b.right},{b.bottom}]")
    return "  " * line.depth + " ".join(parts)


def quoted(text: str) -> str:
    return json.dumps(text, ensure_ascii=False)


def render(view: View, snapshot: SnapshotId) -> tuple[str, ...]:
    return tuple(render_line(line, snapshot) for line in view.lines)


def encoded_size(lines: tuple[str, ...]) -> int:
    """Bytes of the lines as the envelope will encode them (a JSON array of strings)."""
    return len(json.dumps(list(lines), ensure_ascii=False, separators=(",", ":")).encode())


def fit(view: View, snapshot: SnapshotId, budget: int = BUDGET_BYTES - ENVELOPE_RESERVE) -> View:
    """The first degradation that fits. If none does, lines are cut from the end; the snapshot's
    `truncated` counts every line fitting removed, and `folded` says where rows went."""
    last = view
    for candidate in degradations(view):
        if encoded_size(render(candidate, snapshot)) <= budget:
            return candidate
        last = candidate
    rendered = render(last, snapshot)
    keep = len(rendered)
    while keep and encoded_size(rendered[:keep]) > budget:
        keep -= 1
    lines, nodes = last.lines[:keep], last.nodes[:keep]
    return View(last.surface, last.mode, lines, nodes, refs_of(lines, nodes))


def degradations(view: View) -> Iterator[View]:
    yield view
    view = replace(view, lines=tuple(replace(line, detail="") for line in view.lines))
    yield view
    view = replace(
        view, lines=tuple(line if line.ref is not None else replace(line, bounds=None) for line in view.lines)
    )
    yield view
    most = max((line.rows or 0 for line in view.lines if folds(line)), default=0)
    k = most // 2
    while k >= 1:
        yield first_rows(view, k)
        k //= 2
    yield skeleton(view, through_pages=False)


def first_rows(view: View, k: int) -> View:
    """Keep the first `k` rows of every folding collection. A cut line counts on the outermost
    collection that cut it."""
    screen = view.surface.screen
    cut_by: dict[int, int] = {}
    for i, line in enumerate(view.lines):
        if folds(line) and i not in cut_by:
            for group in row_groups(screen, view.nodes, i)[k:]:
                for j in group:
                    cut_by.setdefault(j, i)
    kept = [i for i in range(len(view.lines)) if i not in cut_by]
    counts = Counter(cut_by.values())
    lines = [replace(view.lines[i], folded=view.lines[i].folded + counts[i]) for i in kept]
    nodes = [view.nodes[i] for i in kept]
    return View(view.surface, view.mode, tuple(lines), tuple(nodes), refs_of(lines, nodes))
