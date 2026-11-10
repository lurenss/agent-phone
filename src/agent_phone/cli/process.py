"""`agent-phone` as a process: arguments in, one JSON envelope out, an exit code.

Nothing here raises across the process boundary. A `Refusal` becomes its envelope, and any other
exception becomes the INTERNAL envelope (`envelope.floor_envelope`).
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from agent_phone.adapters.uiautomator2.adb import SubprocessAdb
from agent_phone.adapters.uiautomator2.phone import U2Hub
from agent_phone.cli.args import Command, Invocation, parse_args
from agent_phone.cli.batch import BatchResult, read_steps, run_batch
from agent_phone.cli.batch_args import BatchCommand
from agent_phone.cli.commands import READS, DriverCommand
from agent_phone.cli.driver import Driver, PhoneError, device_lock, open_phone
from agent_phone.cli.flow import FlowResult, run_flow_file
from agent_phone.cli.flow_args import FlowRecordCommand, FlowRunCommand
from agent_phone.cli.flow_record import FlowDraft, record_flow
from agent_phone.cli.policy import load_profiles
from agent_phone.cli.settings import Settings
from agent_phone.cli.trace import Trace, redacted, without_device
from agent_phone.core.act.ledger import unrefunded
from agent_phone.core.commands import devices, server, skills
from agent_phone.core.commands.click import ClickCommand
from agent_phone.core.commands.devices import DevicesCommand
from agent_phone.core.commands.find import FindCommand
from agent_phone.core.commands.get import GetCommand
from agent_phone.core.commands.is_ import IsCommand
from agent_phone.core.commands.scroll import ScrollCommand
from agent_phone.core.commands.server import ServerCommand
from agent_phone.core.commands.set_text import SetTextCommand
from agent_phone.core.commands.skills import SkillsGetCommand, SkillsListCommand
from agent_phone.core.commands.snapshot import SnapshotCommand
from agent_phone.core.device import Serial, select_device
from agent_phone.core.envelope import encode, exit_code, floor_envelope, to_wire
from agent_phone.core.outcome import Outcome, Refusal, Refused
from agent_phone.core.phone import PhoneHub
from agent_phone.core.refs.resolve import RefTarget
from agent_phone.core.snapshot.snapshot import RefToken
from agent_phone.core.wait.clock import Clock, SystemClock

SKILLS_ROOT = Path(__file__).resolve().parents[1] / "skills"


def run(
    argv: Sequence[str],
    hub: PhoneHub,
    settings: Settings,
    out: TextIO,
    clock: Clock | None = None,
    stdin: TextIO | None = None,
) -> int:
    """Run one command line against `hub` and print its envelope to `out`. `stdin` is where a
    batch reads its steps when it is given no file."""
    name, device = "", None
    outcome: Outcome | BatchResult | FlowResult | FlowDraft
    try:
        invocation = parse_args(argv)
        name = invocation.name
        outcome, device = execute(invocation, hub, settings, clock or SystemClock(), stdin or sys.stdin)
    except Refusal as refusal:
        if unrefunded():
            floor = floor_envelope(name, device, refusal, unrefunded=True, mode=settings.permission_mode)
            out.write(encode(floor) + "\n")
            return 1
        outcome = Refused.of(refusal)
    except PhoneError as error:
        outcome, device = error.outcome, error.device
    except Exception as error:
        floor = floor_envelope(name, device, error, unrefunded=unrefunded(), mode=settings.permission_mode)
        out.write(encode(floor) + "\n")
        return 1
    if isinstance(outcome, BatchResult | FlowResult | FlowDraft):
        out.write(encode(outcome.wire()) + "\n")
        return outcome.exit_code
    out.write(encode(to_wire(name, device, outcome, mode=settings.permission_mode)) + "\n")
    return exit_code(outcome)


def execute(
    invocation: Invocation, hub: PhoneHub, settings: Settings, clock: Clock, stdin: TextIO
) -> tuple[Outcome | BatchResult | FlowResult | FlowDraft, Serial | None]:
    """The outcome and the serial the command ran against, None when it chose no device."""
    match invocation.command:
        case DevicesCommand():
            try:
                profiles = tuple(loaded.profile for loaded in load_profiles(settings.state_root))
            except Refusal as refusal:
                return Refused.of(refusal), None
            return devices.run(hub, profiles), None
        case SkillsListCommand() | SkillsGetCommand() as command:
            return skills.run(SKILLS_ROOT, command), None
        case command if isinstance(command, READS):
            with open_phone(
                invocation.serial,
                hub=hub,
                settings=settings,
                clock=clock,
                command=invocation.name,
                ref=ref_of(command),
                first_read=True,
            ) as driver:
                return traced(invocation, command, driver, settings, clock), driver.serial
        case BatchCommand() as command:
            steps = read_steps(command, stdin)
            ref = next((found for step in steps if (found := ref_of(step.command)) is not None), None)
            result = run_batch(steps, invocation.serial, ref, hub, settings, clock)
            return result, result.device
        case FlowRunCommand() as command:
            flow = run_flow_file(command, invocation.serial, hub, settings, clock)
            return flow, flow.device
        case FlowRecordCommand() as command:
            return record_flow(command, settings.permission_mode), None
        case ServerCommand() as command:
            serial = select_device(hub.connected(), invocation.serial, None)
            try:
                if not command.drives:
                    return server.run(hub.server(serial), command), serial
                with device_lock(settings, serial, clock, f"server {command.action.value}"):
                    return server.run(hub.server(serial), command), serial
            except Refusal as refusal:
                raise PhoneError(Refused.of(refusal), serial) from refusal
        case command:
            with open_phone(
                invocation.serial,
                invocation.policies,
                hub=hub,
                settings=settings,
                clock=clock,
                command=invocation.name,
                ref=ref_of(command),
            ) as driver:
                return traced(invocation, command, driver, settings, clock), driver.serial


def traced(
    invocation: Invocation, command: DriverCommand, driver: Driver, settings: Settings, clock: Clock
) -> Outcome:
    """Run the command between its begin line and its end line in the device's trace of the day
    (`cli/trace.py`). A command that raises leaves the begin line alone."""
    argv = redacted(without_device(invocation.argv, invocation.serial), command)
    with Trace.daily(settings.state_root, driver.serial) as trace:
        seq = trace.begin(invocation.name, argv)
        began = clock.now()
        outcome = driver.run(command)
        wire = to_wire(invocation.name, driver.serial, outcome, mode=driver.mode)
        trace.end(seq, command, wire, round((clock.now() - began) * 1000))
    return outcome


def ref_of(command: Command) -> RefToken | None:
    """The ref that names the device when no `-d` does."""
    match command:
        case GetCommand() | IsCommand():
            return command.ref
        case SnapshotCommand() | FindCommand():
            return command.scope.root
        case ClickCommand(target=RefTarget(token)) | SetTextCommand(target=RefTarget(token)):
            return token
        case ScrollCommand(target=RefTarget(token)):
            return token
        case _:
            return None


def main() -> int:
    try:
        settings = Settings.from_environment()
    except Refusal as refusal:
        sys.stdout.write(encode(to_wire("", None, Refused.of(refusal), mode=None)) + "\n")
        return 2
    hub = U2Hub(SubprocessAdb(settings.adb), settings.idle_limit_s)
    return run(sys.argv[1:], hub, settings, sys.stdout)
