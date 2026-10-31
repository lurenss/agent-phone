"""Command-line arguments to a command dataclass. A bad argument is `Refusal(INVALID_ARGS)`, so
the CLI prints the envelope for it like for any other error."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import dataclass
from typing import NoReturn

from agent_phone.core.commands.devices import DevicesCommand
from agent_phone.core.commands.server import ServerAction, ServerCommand
from agent_phone.core.commands.snapshot import SnapshotCommand
from agent_phone.core.device import Serial
from agent_phone.core.outcome import ErrorCode, Refusal

Command = DevicesCommand | ServerCommand | SnapshotCommand


@dataclass(frozen=True, slots=True)
class Invocation:
    name: str
    serial: Serial | None
    command: Command


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise Refusal(ErrorCode.INVALID_ARGS, f"{message}. Run agent-phone --help for the commands.")


def build() -> Parser:
    """`-d` is accepted before the command and after it, because callers put it in both places."""
    device = dict(metavar="SERIAL", help="the adb serial; needed when several devices are ready")
    after = Parser(add_help=False)
    after.add_argument("-d", "--device", default=argparse.SUPPRESS, **device)
    parser = Parser(
        prog="agent-phone",
        description="Drive an Android phone over adb. Every command prints one JSON object.",
    )
    parser.add_argument("-d", "--device", **device)
    commands = parser.add_subparsers(dest="command", metavar="command", required=True, parser_class=Parser)
    commands.add_parser("devices", parents=[after], help="list every device with the facts read from it")
    commands.add_parser("snapshot", parents=[after], help="read the active window as compact lines with refs")
    server = commands.add_parser("server", help="control the on-device server that reads the screen")
    actions = server.add_subparsers(dest="action", metavar="action", required=True, parser_class=Parser)
    actions.add_parser("start", parents=[after], help="start the server, or confirm it runs")
    actions.add_parser("stop", parents=[after], help="stop the server so another tool can use the device")
    actions.add_parser("status", parents=[after], help="say whether the server runs and how long it is idle")
    return parser


def parse_args(argv: Sequence[str]) -> Invocation:
    parsed = build().parse_args(argv)
    match parsed.command:
        case "devices":
            command: Command = DevicesCommand()
        case "snapshot":
            command = SnapshotCommand()
        case "server":
            command = ServerCommand(ServerAction(parsed.action))
    return Invocation(parsed.command, Serial(parsed.device) if parsed.device else None, command)
