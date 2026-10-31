"""`agent-phone` as a process: arguments in, one JSON envelope out, an exit code.

Nothing here raises across the process boundary. A `Refusal` becomes its envelope, and any other
exception becomes the INTERNAL envelope (`envelope.floor_envelope`).
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from typing import TextIO

from agent_phone.adapters.uiautomator2.adb import SubprocessAdb
from agent_phone.adapters.uiautomator2.phone import U2Hub
from agent_phone.cli.args import Invocation, parse_args
from agent_phone.cli.driver import PhoneError, device_lock, open_phone
from agent_phone.cli.settings import Settings
from agent_phone.core.commands import devices, server
from agent_phone.core.commands.devices import DevicesCommand
from agent_phone.core.commands.find import FindCommand
from agent_phone.core.commands.get import GetCommand
from agent_phone.core.commands.is_ import IsCommand
from agent_phone.core.commands.server import ServerCommand
from agent_phone.core.commands.snapshot import SnapshotCommand
from agent_phone.core.device import Serial, select_device
from agent_phone.core.envelope import encode, exit_code, floor_envelope, to_wire
from agent_phone.core.outcome import Outcome, Refusal, Refused
from agent_phone.core.phone import PhoneHub
from agent_phone.core.snapshot.snapshot import RefToken
from agent_phone.core.wait.clock import Clock, SystemClock


def run(
    argv: Sequence[str], hub: PhoneHub, settings: Settings, out: TextIO, clock: Clock | None = None
) -> int:
    """Run one command line against `hub` and print its envelope to `out`."""
    name, device = "", None
    outcome: Outcome
    try:
        invocation = parse_args(argv)
        name = invocation.name
        outcome, device = execute(invocation, hub, settings, clock or SystemClock())
    except Refusal as refusal:
        outcome = Refused.of(refusal)
    except PhoneError as error:
        outcome, device = error.outcome, error.device
    except Exception as error:
        out.write(encode(floor_envelope(name, device, error, unrefunded=False)) + "\n")
        return 1
    out.write(encode(to_wire(name, device, outcome)) + "\n")
    return exit_code(outcome)


def execute(
    invocation: Invocation, hub: PhoneHub, settings: Settings, clock: Clock
) -> tuple[Outcome, Serial | None]:
    """The outcome and the serial the command ran against, None when it chose no device."""
    match invocation.command:
        case DevicesCommand():
            return devices.run(hub, profiles=()), None
        case SnapshotCommand() | FindCommand() | GetCommand() | IsCommand() as command:
            with open_phone(
                invocation.serial,
                hub=hub,
                settings=settings,
                clock=clock,
                command=invocation.name,
                ref=ref_of(command),
            ) as driver:
                return driver.run(command), driver.serial
        case ServerCommand() as command:
            serial = select_device(hub.connected(), invocation.serial, None)
            try:
                if not command.drives:
                    return server.run(hub.server(serial), command), serial
                with device_lock(settings, serial, clock, f"server {command.action.value}"):
                    return server.run(hub.server(serial), command), serial
            except Refusal as refusal:
                raise PhoneError(Refused.of(refusal), serial) from refusal


def ref_of(command: SnapshotCommand | FindCommand | GetCommand | IsCommand) -> RefToken | None:
    """The ref that names the device when no `-d` does."""
    match command:
        case GetCommand() | IsCommand():
            return command.ref
        case SnapshotCommand() | FindCommand():
            return command.scope.root


def main() -> int:
    try:
        settings = Settings.from_environment()
    except Refusal as refusal:
        sys.stdout.write(encode(to_wire("", None, Refused.of(refusal))) + "\n")
        return 2
    hub = U2Hub(SubprocessAdb(settings.adb), settings.idle_limit_s)
    return run(sys.argv[1:], hub, settings, sys.stdout)
