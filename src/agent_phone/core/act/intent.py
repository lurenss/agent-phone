"""What a caller asks act() to do.

Three intents name a target and are planned against the live screen. Every other intent is
already an absolute `InputAction` (`core/phone.py`) and is passed through unchanged, so a key,
a launch or a rotation has one type, not two.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from agent_phone.core.geometry import Point
from agent_phone.core.phone import InputAction, Key, Launch, OpenUri, Rotate, SetClipboard, SetPower, Stop
from agent_phone.core.policy.engine import Grant, Verdict
from agent_phone.core.refs.resolve import Target
from agent_phone.core.role import Role
from agent_phone.core.wait.predicate import Predicate


class Direction(Enum):
    UP = "up"
    DOWN = "down"
    LEFT = "left"
    RIGHT = "right"


@dataclass(frozen=True, slots=True)
class Click:
    target: Target
    long: bool = False


@dataclass(frozen=True, slots=True)
class Fill:
    """Replace a field's text through ACTION_SET_TEXT. Never through the keyboard: the IME
    APK is never installed (A3-1)."""

    target: Target
    text: str


@dataclass(frozen=True, slots=True)
class Scroll:
    """`target` None means the surface's one scrollable collection; several is AMBIGUOUS_TARGET."""

    target: Target | None
    direction: Direction


Intent = Click | Fill | Scroll | Key | Launch | Stop | OpenUri | Rotate | SetPower | SetClipboard


@dataclass(frozen=True, slots=True)
class Request:
    intent: Intent
    grant: Grant = field(default_factory=Grant.none)
    wait_for: tuple[Predicate, ...] = ()
    timeout_ms: int = 5000


@dataclass(frozen=True, slots=True)
class TargetReport:
    ref: str | None
    role: Role
    name: str
    point: Point | None


@dataclass(frozen=True, slots=True)
class ActionReport:
    """What was sent, at what, under which verdict, and what proved it, for the envelope and
    the trace. A secret field's text is never in it."""

    action: InputAction
    target: TargetReport | None
    verdict: Verdict
    verified_by: str | None
