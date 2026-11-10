"""Command-line arguments of `flow`: the file to run, the values of its parameters and the effects
the caller grants it. A flow's steps are argv arrays that `parse_args` parses like any command
line, so there is no second schema (`cli/flow_file.py`)."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

from agent_phone.cli.input_args import COMMIT_HELP
from agent_phone.core.policy.rules import Effect


@dataclass(frozen=True, slots=True)
class FlowRunCommand:
    """`values` are the `--param` pairs as given, so one named twice is still seen."""

    source: Path
    values: tuple[tuple[str, str], ...]
    commit: frozenset[Effect]
    dry_run: bool


@dataclass(frozen=True, slots=True)
class FlowRecordCommand:
    trace: Path
    out: Path


def param(text: str) -> tuple[str, str]:
    name, equals, value = text.partition("=")
    if not equals or not name.isidentifier():
        raise argparse.ArgumentTypeError("a parameter is NAME=VALUE, such as query=battery")
    return name, value


def add_flow(
    commands: argparse._SubParsersAction, after: argparse.ArgumentParser, form: argparse.ArgumentParser
) -> None:
    flow = commands.add_parser("flow", help="replay a job that was written once as a file of steps")
    actions = flow.add_subparsers(dest="action", metavar="action", required=True, parser_class=type(after))
    run = actions.add_parser(
        "run",
        parents=[after],
        help="run the steps of a flow file in one call and print one result",
        description="Run the steps of the TOML file FILE in order, under one device lock, and stop "
        "at the first step that is not ok or whose `expect` does not show. A step's `run` is the "
        "arguments of one command, with a query for its target and never a ref, and `{name}` where "
        "a parameter goes. The file's `grants` cap what its steps may commit, and the flow runs "
        "only when --commit names every effect in `grants`.",
    )
    run.add_argument("file", type=Path, metavar="FILE", help="the flow file")
    run.add_argument(
        "--param",
        action="append",
        type=param,
        default=[],
        metavar="NAME=VALUE",
        help="the value of one parameter the flow declares; repeatable",
    )
    run.add_argument(
        "--commit",
        action="append",
        choices=[e.value for e in Effect],
        default=[],
        metavar="EFFECT",
        help=COMMIT_HELP,
    )
    run.add_argument(
        "--dry-run",
        action="store_true",
        help="grant nothing: run the steps before the first one that would commit, "
        "and send nothing of that one",
    )
    record = actions.add_parser(
        "record",
        parents=[form],
        help="draft a flow file from the trace of what was done by hand",
        description="Read TRACE, a device's trace of one day, and write to --out the draft of a flow "
        "with one step for each input and wait in it that was ok. A target that was named by ref "
        "becomes a query on its role and name, and typed text becomes a parameter. It opens no device.",
    )
    record.add_argument("trace", type=Path, metavar="TRACE", help="<state root>/traces/<serial>/<date>.jsonl")
    record.add_argument("--out", type=Path, required=True, metavar="FILE", help="the flow file to write")


def flow_command(parsed: argparse.Namespace) -> FlowRunCommand | FlowRecordCommand:
    if parsed.action == "record":
        return FlowRecordCommand(parsed.trace, parsed.out)
    return FlowRunCommand(
        parsed.file, tuple(parsed.param), frozenset(Effect(e) for e in parsed.commit), parsed.dry_run
    )
