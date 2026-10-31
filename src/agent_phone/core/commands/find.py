"""`agent-phone find [--role R] [--name X] [--text X] [--value X] [--id X] [--exact]
[--limit N | --count] [--surface S | --window N | --root <ref>]`

Find searches what a snapshot prints: the lines of a compact view. A match is the line the
snapshot shows, with the ref it has there. Matches are listed, never reduced to one, so the
caller can see that a target is not unique before it acts. The matches are recorded as a snapshot
of their own, which owns their refs; `--count` records nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from agent_phone.core.context import Context
from agent_phone.core.outcome import Outcome, Read, Refusal, Refused
from agent_phone.core.query import Query, matches
from agent_phone.core.snapshot.budget import cut_to_budget
from agent_phone.core.snapshot.capture import record
from agent_phone.core.snapshot.scope import Scope, look
from agent_phone.core.snapshot.snapshot import Snapshot
from agent_phone.core.snapshot.surface import select_surface
from agent_phone.core.snapshot.view import Mode, build_view, is_window_line, pick_lines

DEFAULT_LIMIT = 20


@dataclass(frozen=True, slots=True)
class FindCommand:
    query: Query
    limit: int = DEFAULT_LIMIT
    count: bool = False
    scope: Scope = field(default_factory=Scope)


@dataclass(frozen=True, slots=True)
class Found:
    """`count` is every match on the surface. `snapshot` holds the listed ones, as lines, and its
    `truncated` is the matches that `limit` or the byte budget left out. It is None for `--count`."""

    count: int
    snapshot: Snapshot | None


def run(ctx: Context, cmd: FindCommand) -> Outcome:
    try:
        seen = look(ctx, cmd.scope)
        scope = cmd.scope
        surface = select_surface(seen.screen, scope.window, seen.root, scope.pick)
        view = build_view(surface, Mode.COMPACT)
        hits = [
            i
            for i, (line, node) in enumerate(zip(view.lines, view.nodes, strict=True))
            if not is_window_line(surface, line) and matches(cmd.query, seen.screen, seen.screen.node(node))
        ]
        if cmd.count:
            return Read(Found(len(hits), None))
        id = ctx.store.new_id(ctx.info.identity.serial)
        listed = cut_to_budget(pick_lines(view, hits[: cmd.limit]), id)
        snapshot = record(ctx, id, surface, listed, seen.settled, len(hits) - len(listed.lines))
        return Read(Found(len(hits), snapshot))
    except Refusal as refusal:
        return Refused.of(refusal)
