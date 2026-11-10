"""Command-line arguments of the commands that send input, and of the two device reads that go
with them (`clipboard get`, `screenshot`). `args.py` builds the rest of the parser."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from agent_phone.cli.commands import INPUT_TIMEOUT_MS, InputCommand, ScreenshotCommand
from agent_phone.core.act.intent import Direction
from agent_phone.core.commands.click import ClickCommand
from agent_phone.core.commands.clipboard import ClipboardGetCommand, ClipboardSetCommand
from agent_phone.core.commands.launch import LaunchCommand
from agent_phone.core.commands.open_url import OpenUrlCommand
from agent_phone.core.commands.press import PressCommand
from agent_phone.core.commands.rotate import RotateCommand
from agent_phone.core.commands.scroll import ScrollCommand, check_until
from agent_phone.core.commands.set_text import SetTextCommand
from agent_phone.core.commands.stop import StopCommand
from agent_phone.core.device import Package
from agent_phone.core.envelope import After
from agent_phone.core.phone import NAME, KeyName, Orientation
from agent_phone.core.policy.rules import Effect
from agent_phone.core.query import Match, Query
from agent_phone.core.refs.resolve import QueryTarget, RefTarget, Target
from agent_phone.core.role import Role
from agent_phone.core.snapshot.snapshot import RefToken
from agent_phone.core.wait.predicate import Gone, Predicate, Present, Settled

INPUTS = (
    "click",
    "set-text",
    "scroll",
    "press",
    "launch",
    "stop",
    "open-url",
    "rotate",
    "clipboard",
    "screenshot",
)
QUERY_KEY = re.compile(r"(?:^|\s)(name|text|value|role|id)(\^=|\*=|=)")
OPERATORS = {"=": Match.EXACT, "^=": Match.PREFIX, "*=": Match.CONTAINS}


def query_text(text: str) -> Query:
    """`role=button name=Do not disturb`: each key runs to the next key. `^=` matches a prefix and
    `*=` a part, as `Query.describe` prints them, and a value may be in JSON quotes."""
    found = list(QUERY_KEY.finditer(text))
    if not found or text[: found[0].start()].strip():
        raise argparse.ArgumentTypeError(f"{text!r} is not a query such as name=Display or role=button")
    fields: dict[str, str] = {}
    matches = set()
    for at, key in enumerate(found):
        end = found[at + 1].start() if at + 1 < len(found) else len(text)
        value = text[key.end() : end].strip()
        if value.startswith('"'):
            try:
                value = json.loads(value)
            except ValueError as error:
                raise argparse.ArgumentTypeError(f"{value!r} is not a quoted string") from error
        if key[1] in fields or not value:
            raise argparse.ArgumentTypeError(f"{key[1]} is given twice or empty in {text!r}")
        fields[key[1]] = value
        if key[1] in ("name", "text", "value"):
            matches.add(OPERATORS[key[2]])
        elif key[2] != "=":
            raise argparse.ArgumentTypeError(f"{key[1]} takes only =")
    if len(matches) > 1:
        raise argparse.ArgumentTypeError(f"{text!r} mixes =, ^= and *=")
    role = fields.get("role")
    if role is not None and role not in {r.value for r in Role}:
        raise argparse.ArgumentTypeError(f"{role!r} is not a role")
    return Query(
        name=fields.get("name"),
        match=matches.pop() if matches else Match.EXACT,
        role=None if role is None else Role(role),
        resource_id=fields.get("id"),
        text=fields.get("text"),
        value=fields.get("value"),
    )


def target_arg(text: str) -> Target:
    """`@k3x9q:e7` is a ref. Anything else is a query, in the syntax `--wait-for` takes, so a
    query means one thing wherever it is written. A bare word is neither."""
    if text.startswith("@"):
        return RefTarget(RefToken.parse(text))
    try:
        return QueryTarget(query_text(text))
    except argparse.ArgumentTypeError as error:
        raise argparse.ArgumentTypeError(f"{error}. A ref starts with @, such as @k3x9q:e7") from error


def package_name(text: str) -> Package:
    if not NAME.fullmatch(text):
        raise argparse.ArgumentTypeError(f"{text!r} is not a package name as pm list packages prints one")
    return Package(text)


def positive(text: str) -> int:
    if not text.isdigit() or int(text) < 1:
        raise argparse.ArgumentTypeError(f"{text!r} is not a whole number of at least 1")
    return int(text)


def add_inputs(commands: argparse._SubParsersAction, after: argparse.ArgumentParser) -> None:
    target = dict(
        type=target_arg,
        metavar="TARGET",
        help="a ref such as @k3x9q:e12 from a snapshot or find, or a query such as name=Display "
        "that must match one element. After a look, a ref is the safer target",
    )
    click = command(commands, after, "click", "tap an element; a commit needs --commit", commit=True)
    click.add_argument("target", **target)
    click.add_argument("--long", action="store_true", help="hold the touch, as a long press")
    set_text = command(
        commands, after, "set-text", "replace the text of a field, with no keyboard and no tap"
    )
    set_text.add_argument("target", **target)
    set_text.add_argument("text", help="the text the field holds afterwards")
    scroll = command(commands, after, "scroll", "swipe a list; down shows what is below")
    scroll.add_argument("direction", choices=[d.value for d in Direction])
    scroll.add_argument("target", nargs="?", **target)
    scroll.add_argument(
        "--until",
        type=query_text,
        metavar="QUERY",
        help="swipe again until a line that matches shows, up to 10 swipes or the end of the list, and "
        "print the settled screen; the list is named by a query or left out, never by a ref",
    )
    press = command(commands, after, "press", "press a key; enter needs --commit send", commit=True)
    press.add_argument("key", choices=[k.value for k in KeyName])
    for name, about in (("launch", "start an app's launcher screen"), ("stop", "force-stop an app")):
        command(commands, after, name, about).add_argument("package", type=package_name, metavar="PACKAGE")
    open_url = command(
        commands, after, "open-url", "open a link, or an intent:#Intent;action=...;end", commit=True
    )
    open_url.add_argument("uri", metavar="URI")
    open_url.add_argument("--package", type=package_name, help="the app that must open it")
    rotate = command(commands, after, "rotate", "lock the rotation, or hand it back to the sensor with auto")
    rotate.add_argument("orientation", choices=[o.value for o in Orientation])
    clipboard = commands.add_parser("clipboard", help="read or replace the clipboard")
    actions = clipboard.add_subparsers(
        dest="action", metavar="action", required=True, parser_class=type(after)
    )
    actions.add_parser("get", parents=[after], help="print the clipboard's text")
    put = actions.add_parser("set", parents=[after], help="replace the clipboard's text; this is an input")
    put.add_argument("text")
    put.add_argument("--policy", action="append", type=Path, default=[], metavar="FILE", help=POLICY_HELP)
    commands.add_parser(
        "screenshot", parents=[after], help="save the screen as an image under the state root"
    )


POLICY_HELP = "a policy file whose rules apply after the default and the device profile; repeatable"
COMMIT_HELP = (
    f"grant one effect the input commits ({', '.join(effect.value for effect in Effect)}); "
    "only when your user asked for it; repeatable"
)


def command(
    commands: argparse._SubParsersAction,
    after: argparse.ArgumentParser,
    name: str,
    about: str,
    commit: bool = False,
) -> argparse.ArgumentParser:
    """The flags every input shares: what to wait for after it, how long, which policy files, and
    how the `after` snapshot prints."""
    parser = commands.add_parser(name, parents=[after], help=about)
    if commit:
        parser.add_argument(
            "--commit",
            action="append",
            choices=[e.value for e in Effect],
            default=[],
            metavar="EFFECT",
            help=COMMIT_HELP,
        )
    parser.add_argument(
        "--wait-for",
        action="append",
        type=query_text,
        default=[],
        metavar="QUERY",
        help="wait until it shows",
    )
    parser.add_argument(
        "--wait-for-gone",
        action="append",
        type=query_text,
        default=[],
        metavar="QUERY",
        help="wait until it goes",
    )
    parser.add_argument(
        "--settle",
        action="store_true",
        help="wait until the screen stops changing, and print it as the result's after snapshot, with "
        "refs for the next input; use it when you cannot say what the input will show",
    )
    parser.add_argument(
        "--timeout-ms",
        type=positive,
        default=INPUT_TIMEOUT_MS,
        metavar="N",
        help="how long to wait for the target, and then for --wait-for and --settle "
        f"(default {INPUT_TIMEOUT_MS})",
    )
    parser.add_argument("--policy", action="append", type=Path, default=[], metavar="FILE", help=POLICY_HELP)
    parser.add_argument(
        "--after",
        choices=[form.value for form in After],
        default=After.TREE.value,
        help="how the result's after snapshot prints: its tree (default), or with diff only the "
        "lines that the snapshot the input stood on did not print, and the ones it alone printed",
    )
    return parser


def waits(parsed: argparse.Namespace) -> tuple[Predicate, ...]:
    return (
        *(Present(q) for q in parsed.wait_for),
        *(Gone(q) for q in parsed.wait_for_gone),
        *((Settled(),) if parsed.settle else ()),
    )


def until(parsed: argparse.Namespace) -> Query | None:
    """Raise INVALID_ARGS for an `--until` that cannot work, before any device is opened."""
    if parsed.until is not None:
        check_until(parsed.target, waits(parsed))
    return parsed.until


def input_command(parsed: argparse.Namespace) -> InputCommand:
    match parsed.command:
        case "clipboard" if parsed.action == "get":
            return ClipboardGetCommand()
        case "clipboard":
            return ClipboardSetCommand(parsed.text)
        case "screenshot":
            return ScreenshotCommand()
    timing = {"wait_for": waits(parsed), "timeout_ms": parsed.timeout_ms}
    granted = frozenset(Effect(e) for e in getattr(parsed, "commit", []))
    match parsed.command:
        case "click":
            return ClickCommand(parsed.target, parsed.long, granted, **timing)
        case "set-text":
            return SetTextCommand(parsed.target, parsed.text, **timing)
        case "scroll":
            return ScrollCommand(Direction(parsed.direction), parsed.target, **timing, until=until(parsed))
        case "press":
            return PressCommand(KeyName(parsed.key), granted, **timing)
        case "launch":
            return LaunchCommand(parsed.package, **timing)
        case "stop":
            return StopCommand(parsed.package, **timing)
        case "open-url":
            return OpenUrlCommand(parsed.uri, parsed.package, granted, **timing)
        case _:
            return RotateCommand(Orientation(parsed.orientation), **timing)
