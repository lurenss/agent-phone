"""Which window a snapshot describes.

The server dump returns every window (A2-4): the app, the status bar strip, the keyboard, a
dialog, the notification shade. A snapshot describes one surface, the active window by
default, and lists the rest in one line each so the agent knows they exist. Refs exist only
for the surface's nodes, and input goes only to the active window.

The active window is whatever has focus: an app, Settings, a permission dialog, the launcher,
or the system UI itself when the shade or quick settings are pulled down (then the only window
in the dump can be the system UI's, full screen). Nothing here names a package.
"""

from __future__ import annotations

from dataclasses import dataclass

from agent_phone.core.device import Package
from agent_phone.core.geometry import Rect
from agent_phone.core.outcome import ErrorCode, Refusal
from agent_phone.core.screen import NodeId, Screen, Window, WindowId, WindowKind


@dataclass(frozen=True, slots=True)
class OtherWindow:
    id: WindowId
    package: Package
    kind: WindowKind
    bounds: Rect
    nodes: int


@dataclass(frozen=True, slots=True)
class Surface:
    """`root` is the window root, or the drill-down node for `snapshot --root`."""

    screen: Screen
    window: Window
    root: NodeId
    keyboard: bool
    dialog: bool
    others: tuple[OtherWindow, ...]


def select_surface(screen: Screen, window: WindowId | None = None, root: NodeId | None = None) -> Surface:
    """Raise `Refusal(NO_SURFACE)` when no window is active (screen off, empty dump) and none
    was asked for.

    `dialog` is true when the surface window does not cover the display. The policy engine
    reads a dialog's whole text as the context of its buttons (`policy/engine.py`). A `root`
    given without a `window` describes the window that holds it.
    """
    if window is None and root is not None:
        window = screen.node(root).window
    chosen = screen.windows[window] if window is not None else screen.active_window()
    if chosen is None:
        raise Refusal(ErrorCode.NO_SURFACE, "No window has input focus. The screen may be off.")
    display = Rect(0, 0, screen.display.width, screen.display.height)
    others = tuple(
        OtherWindow(w.id, w.package, w.kind, w.bounds, len(screen.subtree(w.root)))
        for w in screen.windows
        if w.id != chosen.id
    )
    return Surface(
        screen=screen,
        window=chosen,
        root=root if root is not None else chosen.root,
        keyboard=any(w.kind is WindowKind.INPUT_METHOD for w in screen.windows),
        dialog=not chosen.bounds.covers(display),
        others=others,
    )
