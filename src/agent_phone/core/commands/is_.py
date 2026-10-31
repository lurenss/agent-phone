"""`agent-phone is <ref> [--property visible|enabled|checked|focused|selected]`

Checks one boolean of the element a ref names, on the live screen. The dump always says, so
`false` is an answer: `is checked` on an element that cannot be checked is false. The file name
has a trailing underscore because `is` is a keyword.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from agent_phone.core.context import Context
from agent_phone.core.outcome import Outcome, Read, Refusal, Refused, Value
from agent_phone.core.refs.live import live_node
from agent_phone.core.screen import Flag
from agent_phone.core.snapshot.snapshot import RefToken


class IsProperty(Enum):
    VISIBLE = "visible"
    ENABLED = "enabled"
    CHECKED = "checked"
    FOCUSED = "focused"
    SELECTED = "selected"


FLAGS = {
    IsProperty.VISIBLE: Flag.VISIBLE,
    IsProperty.ENABLED: Flag.ENABLED,
    IsProperty.CHECKED: Flag.CHECKED,
    IsProperty.FOCUSED: Flag.FOCUSED,
    IsProperty.SELECTED: Flag.SELECTED,
}


@dataclass(frozen=True, slots=True)
class IsCommand:
    ref: RefToken
    property: IsProperty = IsProperty.VISIBLE


def run(ctx: Context, cmd: IsCommand) -> Outcome:
    try:
        _, node = live_node(ctx, cmd.ref)
    except Refusal as refusal:
        return Refused.of(refusal)
    return Read(Value(node.has(FLAGS[cmd.property]), None, cmd.ref, cmd.property.value))
