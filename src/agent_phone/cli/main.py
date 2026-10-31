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
from agent_phone.cli.settings import Settings
from agent_phone.core.commands import devices
from agent_phone.core.commands.devices import DevicesCommand
from agent_phone.core.device import Serial
from agent_phone.core.envelope import encode, exit_code, floor_envelope, to_wire
from agent_phone.core.outcome import Outcome, Refusal, Refused
from agent_phone.core.phone import PhoneHub


def run(argv: Sequence[str], hub: PhoneHub, out: TextIO) -> int:
    """Run one command line against `hub` and print its envelope to `out`."""
    name, device = "", None
    outcome: Outcome
    try:
        invocation = parse_args(argv)
        name = invocation.name
        outcome, device = execute(invocation, hub)
    except Refusal as refusal:
        outcome = Refused.of(refusal)
    except Exception as error:
        out.write(encode(floor_envelope(name, device, error, unrefunded=False)) + "\n")
        return 1
    out.write(encode(to_wire(name, device, outcome)) + "\n")
    return exit_code(outcome)


def execute(invocation: Invocation, hub: PhoneHub) -> tuple[Outcome, Serial | None]:
    """The outcome and the serial the command ran against, None when it chose no device."""
    match invocation.command:
        case DevicesCommand():
            return devices.run(hub, profiles=()), None


def main() -> int:
    try:
        settings = Settings.from_environment()
    except Refusal as refusal:
        sys.stdout.write(encode(to_wire("", None, Refused.of(refusal))) + "\n")
        return 2
    return run(sys.argv[1:], U2Hub(SubprocessAdb(settings.adb)), sys.stdout)
