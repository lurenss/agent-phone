"""Finding elements by what the agent sees.

One `Query` type serves three places: a target that is found on the live screen at action time,
a wait predicate, and `Snapshot.pick` over a snapshot the caller already holds. It matches the
display name the snapshot printed, so a query copied from a snapshot line finds that line.

`matches` judges one node. The caller decides which nodes are candidates, and the observing
commands offer the nodes of a compact view, so a button whose words sit in a child is found
once, as the button, and its child is never a second match.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum

from agent_phone.core.labels import display_name, normalized, shown_values
from agent_phone.core.outcome import ErrorCode, Refusal
from agent_phone.core.role import VALUE_ROLES, Role, role_of
from agent_phone.core.screen import Flag, Node, Screen


class Match(Enum):
    EXACT = "exact"
    PREFIX = "prefix"
    CONTAINS = "contains"


OPERATORS = {Match.EXACT: "=", Match.PREFIX: "^=", Match.CONTAINS: "*="}


@dataclass(frozen=True, slots=True)
class Query:
    """Every set field must hold, and `match` applies to `name`, `text` and `value`, always
    ignoring case and the spacing between words. `name` is the display name, `text` is any
    word the element shows (its name or its detail), `value` is the typed text of a field or
    slider, and `resource_id` is the full id or its entry name."""

    name: str | None = None
    match: Match = Match.EXACT
    role: Role | None = None
    resource_id: str | None = None
    text: str | None = None
    value: str | None = None

    def __post_init__(self) -> None:
        if all(field is None for field in (self.name, self.role, self.resource_id, self.text, self.value)):
            raise Refusal(
                ErrorCode.INVALID_ARGS, "A query needs at least one of name, text, value, role or id."
            )

    def describe(self) -> str:
        """`role=button name="Wi-Fi"`, with `^=` for a prefix match and `*=` for contains."""
        op = OPERATORS[self.match]
        parts = [] if self.role is None else [f"role={self.role.value}"]
        if self.resource_id is not None:
            parts.append(f"id={self.resource_id}")
        for field, value in (("name", self.name), ("text", self.text), ("value", self.value)):
            if value is not None:
                parts.append(f"{field}{op}{json.dumps(value, ensure_ascii=False)}")
        return " ".join(parts)


def Q(
    name: str | None = None,
    *,
    match: Match = Match.EXACT,
    role: Role | None = None,
    id: str | None = None,
    text: str | None = None,
    value: str | None = None,
) -> Query:
    return Query(name=name, match=match, role=role, resource_id=id, text=text, value=value)


def matches(query: Query, screen: Screen, node: Node) -> bool:
    attrs = node.attrs
    role = role_of(attrs)
    if query.role is not None and role is not query.role:
        return False
    if query.resource_id is not None and query.resource_id not in (
        attrs.resource_id,
        attrs.resource_id.rpartition("/")[2],
    ):
        return False
    if query.name is not None and not said(query, query.name, (display_name(screen, node, role),)):
        return False
    if query.text is not None and not said(query, query.text, shown_values(screen, node, role)):
        return False
    return query.value is None or said(query, query.value, typed(node, role))


def typed(node: Node, role: Role) -> tuple[str, ...]:
    """The text a field or slider holds. A secret field holds none that a query can read, so a
    query cannot find a password by guessing it."""
    if role in VALUE_ROLES and Flag.PASSWORD not in node.attrs.flags:
        return (node.attrs.text,)
    return ()


def said(query: Query, wanted: str, candidates: tuple[str, ...]) -> bool:
    want = normalized(wanted)
    for candidate in map(normalized, candidates):
        match query.match:
            case Match.EXACT if candidate == want:
                return True
            case Match.PREFIX if candidate.startswith(want):
                return True
            case Match.CONTAINS if want in candidate:
                return True
    return False
