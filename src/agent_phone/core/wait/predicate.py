"""Conditions a wait polls for. Pure: each is decided from the previous and the current read.

An effect predicate (Present, Gone, Foreground) can prove an action worked, when it was false
before the action and holds after. Settled cannot: a screen settles whether or not the tap
landed.
"""

from __future__ import annotations

from dataclasses import dataclass

from agent_phone.core.device import Package
from agent_phone.core.query import Query
from agent_phone.core.screen import Screen
from agent_phone.core.snapshot.snapshot import RefToken


@dataclass(frozen=True, slots=True)
class Present:
    query: Query


@dataclass(frozen=True, slots=True)
class Gone:
    what: Query | RefToken


@dataclass(frozen=True, slots=True)
class Foreground:
    package: Package


@dataclass(frozen=True, slots=True)
class Settled:
    """Two consecutive reads print the same compact lines. Comparing printed lines, not the raw
    tree, ignores churn the agent cannot see, such as a progress bar's bounds."""


Predicate = Present | Gone | Foreground | Settled


def is_effect(predicate: Predicate) -> bool:
    return not isinstance(predicate, Settled)


def holds(predicate: Predicate, previous: Screen | None, current: Screen) -> bool:
    # TODO: Present/Gone match over the active window with query.matches; Gone(RefToken)
    # resolves the ref's fingerprint with refs.resolve.locate and holds on STALE_REF(GONE);
    # Foreground compares the active window's package; Settled needs `previous`.
    raise NotImplementedError


def describe(predicate: Predicate) -> str:
    """`present name="Create new content"`, as `verified_by` prints it."""
    raise NotImplementedError
