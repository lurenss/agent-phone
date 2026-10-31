"""The 8 KB output budget (A4-1) and the text form of a snapshot line.

Fitting degrades in a fixed order, and each step only removes: details, then bounds on non-ref
lines, then rows beyond the first k of each collection (k halves until it fits, each cut
collection keeps its ref and a `folded` count so the agent can drill), then skeleton. The
snapshot reports `truncated` and how many lines were cut, never a silently short tree.
"""

from __future__ import annotations

from agent_phone.core.snapshot.snapshot import SnapshotId
from agent_phone.core.snapshot.view import Line, View

BUDGET_BYTES = 8 * 1024
ENVELOPE_RESERVE = 512


def render_line(line: Line, snapshot: SnapshotId) -> str:
    """`  @k3x9q:e4 button "<name>" "<detail>" [631,448,1038,564]`

    Indent two spaces per depth. Ref first so an agent can copy it, role, quoted name, then
    quoted detail, `value=`, `#id` when the name is empty, states, `(N rows)`, `(+N)` for
    folded lines, and bounds last.
    """
    raise NotImplementedError


def render(view: View, snapshot: SnapshotId) -> tuple[str, ...]:
    raise NotImplementedError


def encoded_size(lines: tuple[str, ...]) -> int:
    """Bytes of the lines as the envelope will encode them (a JSON array of strings)."""
    raise NotImplementedError


def fit(view: View, snapshot: SnapshotId, budget: int = BUDGET_BYTES - ENVELOPE_RESERVE) -> View:
    # TODO: try each degradation level in order until encoded_size(render(level)) <= budget.
    # The returned view's `refs` holds only refs still printed, so the record stores no ref
    # the agent never saw.
    raise NotImplementedError
