"""What a consumer of the Driver passes, turned into the fields of a command: a target named by
ref, by ref text or by query, the effects it grants, and the predicates it waits for."""

from __future__ import annotations

from collections.abc import Sequence

from agent_phone.core.policy.rules import Effect
from agent_phone.core.query import Query
from agent_phone.core.refs.resolve import QueryTarget, RefTarget, Target
from agent_phone.core.snapshot.snapshot import RefToken
from agent_phone.core.wait.predicate import Foreground, Gone, Predicate, Present, Settled

TargetLike = Target | RefToken | Query | str


def target_of(target: TargetLike) -> Target:
    match target:
        case RefToken():
            return RefTarget(target)
        case Query():
            return QueryTarget(target)
        case str():
            return RefTarget(RefToken.parse(target))
        case _:
            return target


def effects(commit: Effect | Sequence[Effect]) -> frozenset[Effect]:
    return frozenset({commit} if isinstance(commit, Effect) else commit)


def predicates(wait_for: Predicate | Sequence[Predicate]) -> tuple[Predicate, ...]:
    return (wait_for,) if isinstance(wait_for, Present | Gone | Foreground | Settled) else tuple(wait_for)
