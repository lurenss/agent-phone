"""Finding elements by what the agent sees.

One `Query` type serves three places: a target that is found on the live screen at action time,
a wait predicate, and `Snapshot.pick` over a snapshot the caller already holds. It matches the
display name the snapshot printed, so a query copied from a snapshot line finds that line.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from agent_phone.core.role import Role
from agent_phone.core.screen import Node, Screen


class Match(Enum):
    EXACT = "exact"
    PREFIX = "prefix"
    CONTAINS = "contains"


@dataclass(frozen=True, slots=True)
class Query:
    """All set fields must hold. A query with every field None is INVALID_ARGS at the boundary."""

    name: str | None = None
    match: Match = Match.EXACT
    role: Role | None = None
    resource_id: str | None = None

    def describe(self) -> str:
        raise NotImplementedError


def Q(
    name: str | None = None, *, match: Match = Match.EXACT, role: Role | None = None, id: str | None = None
) -> Query:
    return Query(name=name, match=match, role=role, resource_id=id)


def matches(query: Query, screen: Screen, node: Node) -> bool:
    # TODO: compare against labels.display_name (casefold for every Match mode); role via
    # role_of; resource_id matches the full id or its entry name.
    raise NotImplementedError
