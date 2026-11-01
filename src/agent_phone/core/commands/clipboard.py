"""`agent-phone clipboard get` and `agent-phone clipboard set <text>`. Getting reads and changes
nothing. Setting is an input like any other: it spends the refs taken before it."""

from __future__ import annotations

from dataclasses import dataclass

from agent_phone.core.act.act import act
from agent_phone.core.act.intent import Request
from agent_phone.core.context import Context
from agent_phone.core.device import Capability
from agent_phone.core.outcome import ErrorCode, Outcome, Read, Refusal, Refused, Value
from agent_phone.core.phone import SetClipboard


@dataclass(frozen=True, slots=True)
class ClipboardGetCommand:
    pass


@dataclass(frozen=True, slots=True)
class ClipboardSetCommand:
    text: str


def run(ctx: Context, cmd: ClipboardGetCommand | ClipboardSetCommand) -> Outcome:
    if Capability.CLIPBOARD not in ctx.info.capabilities:
        return Refused(ErrorCode.NOT_SUPPORTED, "This backend cannot reach the clipboard.")
    match cmd:
        case ClipboardGetCommand():
            try:
                return Read(Value(ctx.phone.clipboard()))
            except Refusal as refusal:
                return Refused.of(refusal)
        case ClipboardSetCommand(text=text):
            return act(ctx, Request(SetClipboard(text)))
