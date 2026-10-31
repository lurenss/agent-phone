"""Which window a snapshot describes.

The server dump returns every window (A2-4): the app, the status bar strip, the keyboard, a
dialog, the notification shade. A snapshot describes one surface, the active window by
default, and lists the rest in one line each so the agent knows they exist. Refs exist only
for the surface's nodes, and input goes only to the active window.

The active window is whatever has focus: an app, Settings, a permission dialog, the launcher,
or the system UI itself when the shade or quick settings are pulled down (then the only window
in the dump can be the system UI's, full screen). The dump lists it first (A2-7), and a dialog
over an app hides the app beneath it from the dump, so `dialog` is the active window too.
Nothing here names a package.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from agent_phone.core.device import Package
from agent_phone.core.geometry import Rect
from agent_phone.core.outcome import ErrorCode, Refusal
from agent_phone.core.screen import NodeId, Screen, Window, WindowId, WindowKind


class Pick(Enum):
    """Which window `snapshot` describes when the caller names no window id.

    ACTIVE is the window with input focus. DIALOG is the active window when it does not cover
    the display, and nothing otherwise. KEYBOARD is the input method window. SHADE is the
    window of Android's own UI that covers the display: the notification shade and quick
    settings, and also the lock screen, because the dump has no window type to tell them apart.
    ALL describes every window in one tree, each under a line that names it.
    """

    ACTIVE = "active"
    DIALOG = "dialog"
    KEYBOARD = "keyboard"
    SHADE = "shade"
    ALL = "all"


@dataclass(frozen=True, slots=True)
class OtherWindow:
    id: WindowId
    package: Package
    kind: WindowKind
    bounds: Rect
    nodes: int


@dataclass(frozen=True, slots=True)
class Surface:
    """`root` is the window root, or the drill-down node for `snapshot --root`. `more` holds
    the windows after `window` when `pick` is ALL, and is empty otherwise."""

    screen: Screen
    window: Window
    root: NodeId
    keyboard: bool
    dialog: bool
    others: tuple[OtherWindow, ...]
    pick: Pick = Pick.ACTIVE
    more: tuple[Window, ...] = ()

    @property
    def windows(self) -> tuple[Window, ...]:
        """In dump order, so that a window's place in an all-windows tree is its id."""
        return tuple(sorted((self.window, *self.more), key=lambda w: w.id))

    @property
    def roots(self) -> tuple[NodeId, ...]:
        """Where a walk of the surface starts: the drill-down node, else each described window."""
        if self.root != self.window.root:
            return (self.root,)
        return tuple(window.root for window in self.windows)


def select_surface(
    screen: Screen, window: WindowId | None = None, root: NodeId | None = None, pick: Pick = Pick.ACTIVE
) -> Surface:
    """Raise `Refusal(NO_SURFACE)` when the window asked for is not on screen: no window is
    active (screen off, empty dump), `pick` finds nothing, or `window` is not an index of
    this read.

    `dialog` is true when the surface window does not cover the display. The policy engine
    reads a dialog's whole text as the context of its buttons (`policy/engine.py`). A `root`
    given without a `window` describes the window that holds it.
    """
    if window is None and root is not None:
        window = screen.node(root).window
    chosen = window_of(screen, window) if window is not None else pick_window(screen, pick)
    display = Rect(0, 0, screen.display.width, screen.display.height)
    pick = Pick.ACTIVE if window is not None else pick
    rest = tuple(w for w in screen.windows if w.id != chosen.id)
    every = pick is Pick.ALL
    return Surface(
        screen=screen,
        window=chosen,
        root=root if root is not None else chosen.root,
        keyboard=any(w.kind is WindowKind.INPUT_METHOD for w in screen.windows),
        dialog=not chosen.bounds.covers(display),
        others=()
        if every
        else tuple(OtherWindow(w.id, w.package, w.kind, w.bounds, len(screen.subtree(w.root))) for w in rest),
        pick=pick,
        more=rest if every else (),
    )


def window_of(screen: Screen, id: WindowId) -> Window:
    if not 0 <= id < len(screen.windows):
        raise Refusal(
            ErrorCode.NO_SURFACE,
            f"There is no window {id}. {listing(screen)}",
            {"window": id, "windows": len(screen.windows)},
        )
    return screen.windows[id]


def pick_window(screen: Screen, pick: Pick) -> Window:
    active = screen.active_window()
    display = Rect(0, 0, screen.display.width, screen.display.height)
    match pick:
        case Pick.ACTIVE | Pick.ALL:
            found = active
        case Pick.DIALOG:
            found = active if active is not None and not active.bounds.covers(display) else None
        case Pick.KEYBOARD:
            found = next((w for w in screen.windows if w.kind is WindowKind.INPUT_METHOD), None)
        case Pick.SHADE:
            found = next(
                (w for w in screen.windows if w.kind is WindowKind.SYSTEM and w.bounds.covers(display)), None
            )
    if found is None:
        raise Refusal(ErrorCode.NO_SURFACE, absence(screen, pick), {"surface": pick.value})
    return found


def absence(screen: Screen, pick: Pick) -> str:
    if screen.active_window() is None:
        return (
            f"No window has input focus. The screen may be off, or an app may be starting. {listing(screen)}"
        )
    return f"No {pick.value} is on screen. {listing(screen)}"


def listing(screen: Screen) -> str:
    if not screen.windows:
        return "No window is on screen."
    return "Windows: " + ", ".join(f"{w.id} {w.package} ({w.kind.value})" for w in screen.windows) + "."
