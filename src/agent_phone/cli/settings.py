"""What the environment configures, read once at the boundary.

AGENT_PHONE_HOME          state root for locks, snapshots and ledgers (default ~/.agent-phone)
AGENT_PHONE_IDLE_S        seconds without use before the phone stops its server (default 900)
AGENT_PHONE_LOCK_WAIT_S   seconds a command waits for another process to let go of the
                          device before DEVICE_BUSY (default 10)
AGENT_PHONE_PERMISSION_MODE
                          `ask` (the default, also when unset or empty) or `dangerously-skip`. The
                          person who launches the agent sets it, never the agent
                          (`core/policy/mode.py`). Any other value is INVALID_ARGS.
ADB                       the adb binary (default `adb`)
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from agent_phone.core.outcome import ErrorCode, Refusal
from agent_phone.core.policy.mode import PermissionMode
from agent_phone.core.refs.store import LOCK_WAIT_S

IDLE_LIMIT_S = 15 * 60
PERMISSION_MODE_VARIABLE = "AGENT_PHONE_PERMISSION_MODE"
DEFAULT_STATE_ROOT = Path.home() / ".agent-phone"


@dataclass(frozen=True, slots=True)
class Settings:
    state_root: Path = DEFAULT_STATE_ROOT
    idle_limit_s: int = IDLE_LIMIT_S
    lock_wait_s: float = LOCK_WAIT_S
    adb: str | None = None
    permission_mode: PermissionMode = PermissionMode.ASK

    @staticmethod
    def from_environment(env: Mapping[str, str] = os.environ) -> Settings:
        return Settings(
            state_root=Path(env["AGENT_PHONE_HOME"]) if env.get("AGENT_PHONE_HOME") else DEFAULT_STATE_ROOT,
            idle_limit_s=whole(env, "AGENT_PHONE_IDLE_S", IDLE_LIMIT_S, 1),
            lock_wait_s=float(whole(env, "AGENT_PHONE_LOCK_WAIT_S", int(LOCK_WAIT_S), 0)),
            adb=env.get("ADB") or None,
            permission_mode=permission_mode(env),
        )


def whole(env: Mapping[str, str], name: str, default: int, least: int) -> int:
    text = env.get(name)
    if text is None:
        return default
    if not text.isdigit() or int(text) < least:
        raise Refusal(
            ErrorCode.INVALID_ARGS, f"{name} is {text!r}. It must be a whole number of at least {least}."
        )
    return int(text)


def permission_mode(env: Mapping[str, str]) -> PermissionMode:
    """`ask` when the variable is unset or empty. A value that names neither mode is refused, never
    read as the one it looks like: a mistyped `dangerously-skip` that quietly became `ask` would
    leave the user thinking commits were skipped, and one that became `dangerously-skip` would skip
    a gate the user never chose."""
    text = env.get(PERMISSION_MODE_VARIABLE, "")
    if text == "":
        return PermissionMode.ASK
    try:
        return PermissionMode(text)
    except ValueError:
        modes = " or ".join(f"`{mode.value}`" for mode in PermissionMode)
        raise Refusal(
            ErrorCode.INVALID_ARGS,
            f"{PERMISSION_MODE_VARIABLE} is {text!r}. It must be {modes}, or unset for `ask`.",
        ) from None
