"""The permission mode: whether a commit needs the caller's grant.

`ask` is the default. A `Commits` verdict goes out only with a grant for every effect it names, so
the agent must come back to its user for any it lacks. `dangerously-skip` lifts that one condition
and nothing else. A `Denied` verdict, a protected package, a language the policy cannot read
(`LOCALE_UNSUPPORTED`, raised by `classify` before a verdict exists) and every refusal that comes
before the engine judges, such as a stale ref or an occluded target, are the same in both modes.

The mode is process configuration. The CLI reads it once from the environment into `Settings`
(`cli/settings.py`), and `Context` carries it to `act()`. A policy file, a device profile, a command
flag and a batch step have no way to set it.
"""

from __future__ import annotations

from enum import Enum

from agent_phone.core.policy.engine import Commits, Grant, Verdict, require


class PermissionMode(Enum):
    ASK = "ask"
    DANGEROUSLY_SKIP = "dangerously-skip"


def admit(verdict: Verdict, grant: Grant, mode: PermissionMode) -> None:
    """Return when the gate lets the input through, else raise COMMIT_REFUSED or DENIED
    (`engine.require`). Only `dangerously-skip` and only a `Commits` verdict skip `require`: a
    `Denied` verdict reaches it in both modes, and it refuses whatever the grant."""
    if mode is PermissionMode.DANGEROUSLY_SKIP and isinstance(verdict, Commits):
        return
    require(verdict, grant)
