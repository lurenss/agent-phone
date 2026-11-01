"""agent-phone's public API for in-process consumers. The CLI is the other door to the same
commands."""

from agent_phone.cli.driver import Driver, PhoneError, open_phone
from agent_phone.core.act.intent import Direction
from agent_phone.core.device import Package
from agent_phone.core.phone import KeyName, Orientation
from agent_phone.core.policy.rules import Effect
from agent_phone.core.query import Match, Q, Query
from agent_phone.core.role import Role
from agent_phone.core.snapshot.snapshot import Snapshot
from agent_phone.core.wait.predicate import Foreground, Gone, Present, Settled

__all__ = [
    "Direction",
    "Driver",
    "Effect",
    "Foreground",
    "Gone",
    "KeyName",
    "Match",
    "Orientation",
    "Package",
    "PhoneError",
    "Present",
    "Q",
    "Query",
    "Role",
    "Settled",
    "Snapshot",
    "open_phone",
]
