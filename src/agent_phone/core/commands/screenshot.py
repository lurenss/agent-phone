"""`agent-phone screenshot`. Evidence for a human, never part of the agent's loop (A1-4). The
image goes to a file under the state root, and the envelope carries its path. It sends no input,
so no ref changes."""

from __future__ import annotations

import os
from pathlib import Path

from agent_phone.core.context import Context
from agent_phone.core.device import Capability
from agent_phone.core.outcome import ErrorCode, Outcome, Read, Refusal, Refused, Value


def run(ctx: Context, path: Path) -> Outcome:
    if Capability.SCREENSHOT not in ctx.info.capabilities:
        return Refused(ErrorCode.NOT_SUPPORTED, "This backend cannot take a screenshot.")
    try:
        image = ctx.phone.screenshot()
    except Refusal as refusal:
        return Refused.of(refusal)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as file:
        file.write(image)
    return Read(Value(str(path)))
