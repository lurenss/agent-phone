"""`agent-phone server start|stop|status`. The server holds the device's one UiAutomation client
(A3-4), so `stop` is also how another tool, such as an old `uiautomator dump` script, gets the
device. Each action prints the status that follows it."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from agent_phone.core.outcome import Outcome, Read, Refusal, Refused
from agent_phone.core.phone import BackendServer


class ServerAction(Enum):
    START = "start"
    STOP = "stop"
    STATUS = "status"


@dataclass(frozen=True, slots=True)
class ServerCommand:
    action: ServerAction

    @property
    def drives(self) -> bool:
        """`start` and `stop` change the device's one UiAutomation client, so they take the
        device lock. `status` only looks."""
        return self.action is not ServerAction.STATUS


def run(server: BackendServer, cmd: ServerCommand) -> Outcome:
    try:
        match cmd.action:
            case ServerAction.START:
                return Read(server.start())
            case ServerAction.STOP:
                return Read(server.stop())
            case ServerAction.STATUS:
                return Read(server.status())
    except Refusal as refusal:
        return Refused.of(refusal)
