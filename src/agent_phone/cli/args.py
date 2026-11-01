"""Command-line arguments to a command dataclass. A bad argument is `Refusal(INVALID_ARGS)`, so
the CLI prints the envelope for it like for any other error."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

from agent_phone.cli.commands import InputCommand
from agent_phone.cli.input_args import INPUTS, add_inputs, input_command
from agent_phone.cli.wait_args import add_wait, wait_command
from agent_phone.core.commands.devices import DevicesCommand
from agent_phone.core.commands.find import DEFAULT_LIMIT, FindCommand
from agent_phone.core.commands.get import GetCommand, GetProperty
from agent_phone.core.commands.is_ import IsCommand, IsProperty
from agent_phone.core.commands.server import ServerAction, ServerCommand
from agent_phone.core.commands.skills import SKILLS, SkillsGetCommand, SkillsListCommand
from agent_phone.core.commands.snapshot import SnapshotCommand
from agent_phone.core.commands.wait import WaitCommand
from agent_phone.core.device import Serial
from agent_phone.core.outcome import ErrorCode, Refusal
from agent_phone.core.query import Match, Query
from agent_phone.core.role import Role
from agent_phone.core.screen import WindowId
from agent_phone.core.snapshot.scope import SETTLE_TIMEOUT_MS, Scope
from agent_phone.core.snapshot.snapshot import RefToken
from agent_phone.core.snapshot.surface import Pick
from agent_phone.core.snapshot.view import Mode

Command = (
    DevicesCommand
    | ServerCommand
    | SnapshotCommand
    | FindCommand
    | GetCommand
    | IsCommand
    | WaitCommand
    | SkillsListCommand
    | SkillsGetCommand
    | InputCommand
)
SKILL_NAMES = {name: skill for skill in SKILLS for name in (skill.name, skill.alias)}


@dataclass(frozen=True, slots=True)
class Invocation:
    """`policies` are the caller's policy files, which only input commands take."""

    name: str
    serial: Serial | None
    command: Command
    policies: tuple[Path, ...] = ()


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise Refusal(ErrorCode.INVALID_ARGS, f"{message}. Run agent-phone --help for the commands.")


def whole_number(text: str) -> int:
    if not text.isdigit():
        raise argparse.ArgumentTypeError(f"{text!r} is not a whole number")
    return int(text)


def positive_number(text: str) -> int:
    number = whole_number(text)
    if number < 1:
        raise argparse.ArgumentTypeError(f"{text!r} is not at least 1")
    return number


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
    add_snapshot(commands, after)
    add_find(commands, after)
    add_property(commands, after, "get", GetProperty, GetProperty.TEXT, "read one property of an element")
    add_property(commands, after, "is", IsProperty, IsProperty.VISIBLE, "check one boolean of an element")
    server = commands.add_parser("server", help="control the on-device server that reads the screen")
    actions = server.add_subparsers(dest="action", metavar="action", required=True, parser_class=Parser)
    actions.add_parser("start", parents=[after], help="start the server, or confirm it runs")
    actions.add_parser("stop", parents=[after], help="stop the server so another tool can use the device")
    actions.add_parser("status", parents=[after], help="say whether the server runs and how long it is idle")
    add_wait(commands, after)
    add_inputs(commands, after)
    add_skills(commands)
    return parser


def add_skills(commands: argparse._SubParsersAction) -> None:
    """They read only the package, so they take no device."""
    skills = commands.add_parser(
        "skills", help="print the usage guides for agents that ship with agent-phone"
    )
    actions = skills.add_subparsers(dest="action", metavar="action", required=True, parser_class=Parser)
    actions.add_parser("list", help="list the guides, each with its name, alias and summary")
    get = actions.add_parser("get", help="print one guide; its Markdown is data.content")
    get.add_argument(
        "name",
        nargs="?",
        choices=list(SKILL_NAMES),
        default=SKILLS[0].name,
        help=f"the guide's name or alias (default {SKILLS[0].name})",
    )


def add_scope(parser: Parser, what: str) -> None:
    """The three ways to say which part of the screen a command reads. They answer one question,
    so at most one of them may be given."""
    where = parser.add_mutually_exclusive_group()
    where.add_argument(
        "--surface",
        choices=[pick.value for pick in Pick],
        default=Pick.ACTIVE.value,
        help=f"which window {what}: the active one (default), a dialog, the keyboard, "
        "the full-screen system window (notification shade), or every window",
    )
    where.add_argument(
        "--window",
        type=whole_number,
        metavar="N",
        help=f"{what} the window that `others` lists under this id, which is its place in the dump",
    )
    where.add_argument(
        "--root",
        type=RefToken.parse,
        metavar="REF",
        help=f"{what} only the subtree under this ref, and keep the ref numbers",
    )


def scope_of(parsed: argparse.Namespace) -> Scope:
    window = None if parsed.window is None else WindowId(parsed.window)
    return Scope(Pick(parsed.surface), window, parsed.root)


def add_snapshot(commands: argparse._SubParsersAction, after: Parser) -> None:
    snapshot = commands.add_parser(
        "snapshot", parents=[after], help="read the active window as compact lines with refs"
    )
    modes = snapshot.add_mutually_exclusive_group()
    snapshot.set_defaults(mode=Mode.COMPACT.value)
    for mode, about in (
        (Mode.COMPACT, "every element that takes input and every text no such element owns (default)"),
        (Mode.SKELETON, "the outline: collections fold their rows into a count, drill in with --root"),
        (Mode.FULL, "every node of the window, including the ones with no words"),
    ):
        modes.add_argument(f"--{mode.value}", dest="mode", action="store_const", const=mode.value, help=about)
    snapshot.add_argument(
        "--settle",
        action="store_true",
        help="read until two reads in a row print the same lines, and say whether they did",
    )
    snapshot.add_argument(
        "--timeout-ms",
        type=whole_number,
        default=SETTLE_TIMEOUT_MS,
        metavar="N",
        help=f"how long --settle may take before it gives up (default {SETTLE_TIMEOUT_MS})",
    )
    add_scope(snapshot, "to describe")


def add_find(commands: argparse._SubParsersAction, after: Parser) -> None:
    find = commands.add_parser(
        "find",
        parents=[after],
        help="list the lines of a snapshot that match, with their refs",
        description="Search what a snapshot prints. Give at least one of --role, --name, --text, "
        "--value and --id. Every match is listed with the ref it has in the snapshot this records.",
    )
    find.add_argument("--role", choices=[role.value for role in Role], help="the element's role")
    find.add_argument("--name", help="the name the snapshot prints for the element")
    find.add_argument("--text", help="any word the element shows, its name or its detail")
    find.add_argument("--value", help="the text typed into a field or slider")
    find.add_argument("--id", help="the resource-id, in full or its entry name after the slash")
    find.add_argument(
        "--exact", action="store_true", help="compare name, text and value whole instead of as a part"
    )
    size = find.add_mutually_exclusive_group()
    size.add_argument(
        "--limit",
        type=positive_number,
        default=DEFAULT_LIMIT,
        metavar="N",
        help=f"list at most N matches (default {DEFAULT_LIMIT}); the count still says how many there are",
    )
    size.add_argument("--count", action="store_true", help="print only how many match, and record nothing")
    add_scope(find, "to search")


def add_property(
    commands: argparse._SubParsersAction,
    after: Parser,
    name: str,
    properties: type[GetProperty] | type[IsProperty],
    default: GetProperty | IsProperty,
    help: str,
) -> None:
    """`get` and `is` have one shape: a ref, and which of its properties to read live."""
    command = commands.add_parser(
        name,
        parents=[after],
        help=f"{help}, live",
        description=f"{help[0].upper()}{help[1:]} on the live screen. The ref is checked first, "
        "and the element must still be there exactly once.",
    )
    command.add_argument("ref", type=RefToken.parse, metavar="REF", help="a ref such as @k3x9q:e12")
    command.add_argument(
        "--property",
        choices=[member.value for member in properties],
        default=default.value,
        help=f"which property (default {default.value})",
    )


def query_of(parsed: argparse.Namespace) -> Query:
    return Query(
        name=parsed.name,
        match=Match.EXACT if parsed.exact else Match.CONTAINS,
        role=None if parsed.role is None else Role(parsed.role),
        resource_id=parsed.id,
        text=parsed.text,
        value=parsed.value,
    )


def parse_args(argv: Sequence[str]) -> Invocation:
    parsed = build().parse_args(argv)
    match parsed.command:
        case "devices":
            command: Command = DevicesCommand()
        case "snapshot":
            command = SnapshotCommand(
                mode=Mode(parsed.mode),
                settle=parsed.settle,
                scope=scope_of(parsed),
                timeout_ms=parsed.timeout_ms,
            )
        case "find":
            command = FindCommand(query_of(parsed), parsed.limit, parsed.count, scope_of(parsed))
        case "get":
            command = GetCommand(parsed.ref, GetProperty(parsed.property))
        case "is":
            command = IsCommand(parsed.ref, IsProperty(parsed.property))
        case "wait":
            command = wait_command(parsed)
        case "server":
            command = ServerCommand(ServerAction(parsed.action))
        case "skills" if parsed.action == "list":
            command = SkillsListCommand()
        case "skills":
            command = SkillsGetCommand(SKILL_NAMES[parsed.name])
        case name if name in INPUTS:
            command = input_command(parsed)
    serial = Serial(parsed.device) if parsed.device else None
    name = parsed.command if parsed.command != "clipboard" else f"clipboard {parsed.action}"
    return Invocation(name, serial, command, tuple(getattr(parsed, "policy", ())))
