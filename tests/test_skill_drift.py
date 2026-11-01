"""The shipped guide names only commands and flags the parser has, and it shows every command the
parser has. A guide that drifts from the parser teaches an agent a call that fails, or hides a
command from it."""

import argparse
import re
import shlex

from agent_phone.cli.args import Parser, build, parse_args
from agent_phone.cli.process import SKILLS_ROOT
from agent_phone.core.outcome import Refusal

FENCE = re.compile(r"^```[^\n]*\n(.*?)^```", re.S | re.M)
SPAN = re.compile(r"`([^`\n]+)`")
HELP = {"-h", "--help"}


def subcommands(parser: argparse.ArgumentParser) -> dict[str, Parser]:
    found = [action for action in parser._actions if isinstance(action, argparse._SubParsersAction)]
    return dict(found[0].choices) if found else {}


def options_of(parser: argparse.ArgumentParser) -> dict[str, argparse.Action]:
    return {flag: action for action in parser._actions for flag in action.option_strings}


def leaves(parser: argparse.ArgumentParser, path: tuple[str, ...] = ()) -> dict[tuple[str, ...], Parser]:
    """Every command path the parser runs, such as ("server", "stop"), with its parser."""
    children = subcommands(parser)
    if not children:
        return {path: parser}
    found: dict[tuple[str, ...], Parser] = {}
    for name, child in children.items():
        found |= leaves(child, (*path, name))
    return found


ROOT_PARSER = build()
LEAVES = leaves(ROOT_PARSER)
EVERY_OPTION = {flag: action for leaf in LEAVES.values() for flag, action in options_of(leaf).items()}


def code_pieces(text: str) -> list[str]:
    """Each line of a fenced block, then each inline code span outside the blocks."""
    lines = [line for block in FENCE.findall(text) for line in block.splitlines()]
    return lines + SPAN.findall(FENCE.sub("", text))


def full_command(argv: list[str]) -> tuple[str, ...] | None:
    """The command path that `agent-phone <argv>` runs, or None when the parser refuses it."""
    try:
        parse_args(argv)
    except Refusal:
        return None
    parsed = ROOT_PARSER.parse_args(argv)
    return (parsed.command, *([parsed.action] if hasattr(parsed, "action") else []))


def options_known(words: list[str]) -> bool:
    """A fragment such as `find --root` or `--surface dialog`: the command words must lead to a
    parser, and each flag, and the choice after a flag that has choices, must belong to it. A
    fragment that names no command may use the flags of any command."""
    parser, options, rest = ROOT_PARSER, EVERY_OPTION, words
    while rest and rest[0] in subcommands(parser):
        parser = subcommands(parser)[rest[0]]
        options = options_of(parser)
        rest = rest[1:]
    if subcommands(parser) and rest and not rest[0].startswith("-"):
        return False
    for at, word in enumerate(rest):
        if not word.startswith("-"):
            continue
        action = options.get(word)
        if action is None:
            return False
        value = rest[at + 1] if at + 1 < len(rest) else None
        if action.choices and value is not None and not value.startswith("-") and value not in action.choices:
            return False
    return True


def drift(text: str) -> tuple[list[str], set[tuple[str, ...]]]:
    """The code pieces that name a command, flag or choice the parser lacks, and the command paths
    that the text shows as a whole `agent-phone ...` call."""
    unknown: list[str] = []
    shown: set[tuple[str, ...]] = set()
    for piece in code_pieces(text):
        first = piece.split()[0] if piece.split() else ""
        if first != "agent-phone" and first not in subcommands(ROOT_PARSER) and not first.startswith("-"):
            continue
        words = shlex.split(piece, comments=True)
        if first == "agent-phone" and not HELP.intersection(words):
            path = full_command(words[1:])
            if path is None:
                unknown.append(piece)
            else:
                shown.add(path)
        elif not options_known(words[1:] if first == "agent-phone" else words):
            unknown.append(piece)
    return unknown, shown


def test_drift_catches_planted_names():
    planted = [
        "`agent-phone snapshot --sideways`",
        "`snapshot --limit 3`",
        "`--comit`",
        "```bash\nagent-phone tap @k3x9q:e1\n```",
        "`--surface popup`",
        "`agent-phone get e4`",
        "`agent-phone server reboot --help`",
    ]
    for text in planted:
        assert drift(text)[0], f"{text!r} names something the parser lacks"
    fine = (
        "`agent-phone snapshot --settle` `find --root` `--surface dialog` `-d <serial>` "
        "`agent-phone find --help` `adb shell am start -a x` `STALE_REF` `@k3x9q:e4`"
    )
    assert drift(fine) == ([], {("snapshot",)})


def test_coverage_catches_a_command_the_text_never_shows():
    _, shown = drift("```bash\nagent-phone devices\nagent-phone server stop\n```\n`server status`")
    assert shown == {("devices",), ("server", "stop")}
    assert ("server", "status") in set(LEAVES) - shown


def test_the_guide_names_only_what_the_parser_has_and_shows_every_command():
    unknown, shown = drift((SKILLS_ROOT / "agent-phone" / "SKILL.md").read_text(encoding="utf-8"))
    assert unknown == [], f"the guide names commands or flags the parser lacks: {unknown}"
    missing = sorted(" ".join(path) for path in set(LEAVES) - shown)
    assert missing == [], f"the guide never shows these commands as an agent-phone call: {missing}"
