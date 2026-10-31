"""Command-line arguments to a command dataclass. A bad argument is `Refusal(INVALID_ARGS)`, so
the CLI prints the envelope for it like for any other error."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import dataclass
from typing import NoReturn

from agent_phone.core.commands.devices import DevicesCommand
from agent_phone.core.commands.server import ServerAction, ServerCommand
from agent_phone.core.device import Serial
from agent_phone.core.outcome import ErrorCode, Refusal

Command = DevicesCommand | ServerCommand


@dataclass(frozen=True, slots=True)
class Invocation:
    name: str
    serial: Serial | None
    command: Command


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise Refusal(ErrorCode.INVALID_ARGS, f"{message}. Run agent-phone --help for the commands.")


def build() -> Parser:
    parser = Parser(
        prog="agent-phone",
        description="Drive an Android phone over adb. Every command prints one JSON object.",
    )
    parser.add_argument(
        "-d", "--device", metavar="SERIAL", help="the adb serial; needed when several devices are ready"
    )
    commands = parser.add_subparsers(dest="command", metavar="command", required=True, parser_class=Parser)
    commands.add_parser("devices", help="list every device with the facts read from it")
    server = commands.add_parser("server", help="control the on-device server that reads the screen")
    actions = server.add_subparsers(dest="action", metavar="action", required=True, parser_class=Parser)
    actions.add_parser("start", help="start the server, or confirm it runs")
    actions.add_parser("stop", help="stop the server so another tool can use the device")
    actions.add_parser("status", help="say whether the server runs and how long it has been idle")
    return parser


def parse_args(argv: Sequence[str]) -> Invocation:
    parsed = build().parse_args(argv)
    match parsed.command:
        case "devices":
            command: Command = DevicesCommand()
        case "server":
            command = ServerCommand(ServerAction(parsed.action))
    return Invocation(parsed.command, Serial(parsed.device) if parsed.device else None, command)
