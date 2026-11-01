"""How much of the screen the engine reads for an input.

A new kind of input must be named here. `reads_of` has no default, so one that is not named
fails the first time it is judged, instead of reading nothing and passing every deny rule.
"""

from __future__ import annotations

from enum import Enum
from typing import assert_never

from agent_phone.core.phone import (
    Activate,
    InputAction,
    Key,
    KeyName,
    Launch,
    LongPress,
    OpenUri,
    Rotate,
    SetClipboard,
    SetPower,
    SetText,
    Stop,
    Swipe,
    Tap,
)


class Reads(Enum):
    """What the engine reads of the screen for an input."""

    NOTHING = "nothing"
    DENIALS = "denials"
    EVERYTHING = "everything"


def reads_of(action: InputAction) -> Reads:
    """A tap and Enter act on an element, so commit rules read it. Enter is judged like a tap on
    the view that has focus. A set-text and a scroll act on an element too, but they commit
    nothing, so only deny rules read it. Back, home and recents read nothing, so that a deny rule
    cannot trap the agent on a screen. Launch, stop, a link, a rotation and the clipboard act on no
    element of the screen."""
    match action:
        case Tap() | LongPress() | Activate() | Key(key=KeyName.ENTER):
            return Reads.EVERYTHING
        case SetText() | Swipe():
            return Reads.DENIALS
        case Key() | Launch() | Stop() | OpenUri() | Rotate() | SetPower() | SetClipboard():
            return Reads.NOTHING
        case _:
            assert_never(action)
