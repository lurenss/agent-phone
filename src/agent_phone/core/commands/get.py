"""`agent-phone get <ref> [--property text|value|bounds|states]`

Reads one property of the element a ref names, from the live screen. It records no snapshot and
sends no input, so the refs of earlier snapshots stay as they were.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from agent_phone.core.context import Context
from agent_phone.core.labels import shown_values, typed_text
from agent_phone.core.outcome import Outcome, Read, Refusal, Refused, Value
from agent_phone.core.refs.live import live_node
from agent_phone.core.role import role_of
from agent_phone.core.screen import Node, Screen
from agent_phone.core.snapshot.snapshot import RefToken
from agent_phone.core.snapshot.view import State, states_of


class GetProperty(Enum):
    TEXT = "text"
    VALUE = "value"
    BOUNDS = "bounds"
    STATES = "states"


@dataclass(frozen=True, slots=True)
class GetCommand:
    ref: RefToken
    property: GetProperty = GetProperty.TEXT


def run(ctx: Context, cmd: GetCommand) -> Outcome:
    try:
        screen, node = live_node(ctx, cmd.ref)
    except Refusal as refusal:
        return Refused.of(refusal)
    return Read(Value(property_of(screen, node, cmd.property), None, cmd.ref, cmd.property.value))


def property_of(
    screen: Screen, node: Node, which: GetProperty
) -> str | tuple[int, ...] | tuple[str, ...] | None:
    attrs = node.attrs
    match which:
        case GetProperty.TEXT:
            return typed_text(node) or ", ".join(shown_values(screen, node, role_of(attrs)))
        case GetProperty.VALUE:
            return typed_text(node)
        case GetProperty.BOUNDS:
            b = attrs.bounds
            return (b.left, b.top, b.right, b.bottom)
        case GetProperty.STATES:
            states = states_of(attrs)
            return tuple(state.value for state in State if state in states)
