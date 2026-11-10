"""What each input needs from a backend. A new kind of input, or a new key, must be named here:
`required` has no default, so one that is not named fails the first time act() asks, instead of
reaching a backend that cannot do it."""

from __future__ import annotations

from typing import assert_never

from agent_phone.core.device import Capability
from agent_phone.core.outcome import ErrorCode, Refusal
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


def required(action: InputAction) -> Capability | None:
    """What an input needs from a backend beyond `read`, or None when every backend has it."""
    match action:
        case Tap() | LongPress() | Swipe():
            return Capability.POINT_INPUT
        case Activate():
            return Capability.SEMANTIC_CLICK
        case Key(key=KeyName.BACK):
            return Capability.KEY_BACK
        case Key(key=KeyName.RECENTS):
            return Capability.KEY_RECENTS
        case OpenUri(uri=uri) if uri.casefold().startswith("intent:"):
            return Capability.INTENT_LINKS
        case Rotate():
            return Capability.ROTATE
        case SetPower():
            return Capability.POWER
        case SetClipboard():
            return Capability.CLIPBOARD
        case Key(key=KeyName.HOME | KeyName.ENTER) | SetText() | Launch() | Stop() | OpenUri():
            return None
        case _:
            assert_never(action)


def refuse_unsupported(action: InputAction, capabilities: frozenset[Capability]) -> None:
    need = required(action)
    if need is not None and need not in capabilities:
        raise Refusal(
            ErrorCode.NOT_SUPPORTED,
            f"This backend has no {need.value}, which this input needs. Nothing was sent. "
            "`agent-phone devices` lists what each device can do.",
            {"capability": need.value},
        )
