"""Conditions a wait polls for. Pure: each is decided from the previous and the current read.

An effect predicate (Present, Gone, Foreground) can prove an action worked, when it was false
before the action and holds after. Settled cannot: a screen settles whether or not the tap
landed.
"""

from __future__ import annotations

from dataclasses import dataclass

from agent_phone.core.device import Package
from agent_phone.core.outcome import ErrorCode, Refusal
from agent_phone.core.query import Query, matches
from agent_phone.core.screen import Screen, WindowId
from agent_phone.core.snapshot.budget import render
from agent_phone.core.snapshot.snapshot import RefToken, SnapshotId
from agent_phone.core.snapshot.surface import Pick, select_surface
from agent_phone.core.snapshot.view import Mode, build_view


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
    """Two consecutive reads print the same compact lines of the surface that `pick` and
    `window` name. Comparing printed lines, not the raw tree, ignores churn the agent cannot
    see, such as a progress bar's bounds. A read with no such surface is not settled, so
    `Settled(Pick.DIALOG)` also waits for a dialog to appear."""

    pick: Pick = Pick.ACTIVE
    window: WindowId | None = None


Predicate = Present | Gone | Foreground | Settled


def is_effect(predicate: Predicate) -> bool:
    return not isinstance(predicate, Settled)


SETTLE_ID = SnapshotId("00000")
"""Lines are compared as printed, and a printed ref holds the snapshot id, so every read is
rendered under the same one."""


def holds(predicate: Predicate, previous: Screen | None, current: Screen) -> bool:
    """Present and Gone match the lines of a compact view of the active window, as `find` does.
    A read with no active window decides neither, so Gone does not hold during a transition.
    Gone by ref needs the ref's stored fingerprint and arrives with the wait command (unit 5)."""
    match predicate:
        case Settled():
            if previous is None:
                return False
            before, now = (printed_lines(screen, predicate) for screen in (previous, current))
            return before is not None and before == now
        case Present(query=query):
            return shown(query, current) is True
        case Gone(what=Query() as query):
            return shown(query, current) is False
        case Gone(what=token):
            raise Refusal(
                ErrorCode.NOT_SUPPORTED, f"Waiting for {token} to go is not supported yet. Wait by query."
            )
        case Foreground(package=package):
            active = current.active_window()
            return active is not None and active.package == package


def shown(query: Query, screen: Screen) -> bool | None:
    """Whether a line of the active window matches, or None when no window has focus."""
    try:
        view = build_view(select_surface(screen), Mode.COMPACT)
    except Refusal:
        return None
    return any(matches(query, screen, screen.node(node)) for node in view.nodes)


def printed_lines(screen: Screen, settled: Settled) -> tuple[str, ...] | None:
    try:
        surface = select_surface(screen, settled.window, None, settled.pick)
    except Refusal:
        return None
    return render(build_view(surface, Mode.COMPACT), SETTLE_ID)


def describe(predicate: Predicate) -> str:
    """`present name="Create new content"`, as `verified_by` prints it."""
    match predicate:
        case Present(query=query):
            return f"present {query.describe()}"
        case Gone(what=Query() as query):
            return f"gone {query.describe()}"
        case Gone(what=token):
            return f"gone {token}"
        case Foreground(package=package):
            return f"foreground {package}"
        case Settled():
            return "settled"
