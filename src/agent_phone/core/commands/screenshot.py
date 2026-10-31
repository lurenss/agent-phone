"""`agent-phone screenshot <path>`. Evidence for a human, never part of the agent's loop (A1-4).
The PNG goes to the given path; the envelope carries the path, the device and the epoch."""

from __future__ import annotations

from pathlib import Path

from agent_phone.core.context import Context
from agent_phone.core.outcome import Outcome


def run(ctx: Context, path: Path) -> Outcome:
    # TODO: NOT_SUPPORTED without Capability.SCREENSHOT; bytes = ctx.phone.screenshot();
    #   write; Read(Value(str(path)))
    raise NotImplementedError
