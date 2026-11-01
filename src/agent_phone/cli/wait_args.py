"""Command-line arguments of `wait`. Its queries and package names parse with the same functions
as `--wait-for`, `--wait-for-gone` and the package of `launch`, so a query means one thing
wherever it is written."""

from __future__ import annotations

import argparse

from agent_phone.cli.input_args import package_name, positive, query_text
from agent_phone.core.commands.wait import WAIT_TIMEOUT_MS, WaitCommand, require_condition
from agent_phone.core.wait.predicate import Foreground, Gone, Present, Settled


def add_wait(commands: argparse._SubParsersAction, after: argparse.ArgumentParser) -> None:
    wait = commands.add_parser(
        "wait",
        parents=[after],
        help="read the screen until conditions hold, and print the screen it ended on",
        description="Read the screen until every condition holds on one read, then print that read as "
        "a snapshot with refs. Give at least one of --for, --gone, --app and --settled. It sends no "
        "input. On a timeout the error's details.after is the last read.",
    )
    wait.add_argument(
        "--for",
        dest="shown",
        action="append",
        type=query_text,
        default=[],
        metavar="QUERY",
        help="a line that matches shows, such as 'name=Brightness'; repeatable",
    )
    wait.add_argument(
        "--gone",
        action="append",
        type=query_text,
        default=[],
        metavar="QUERY",
        help="no line matches; repeatable",
    )
    wait.add_argument(
        "--app",
        type=package_name,
        metavar="PACKAGE",
        help="the window that has focus belongs to this app",
    )
    wait.add_argument(
        "--settled",
        action="store_true",
        help="two reads in a row print the same lines",
    )
    wait.add_argument(
        "--timeout-ms",
        type=positive,
        default=WAIT_TIMEOUT_MS,
        metavar="N",
        help=f"how long to wait before the TIMEOUT error (default {WAIT_TIMEOUT_MS})",
    )


def wait_command(parsed: argparse.Namespace) -> WaitCommand:
    """Raise INVALID_ARGS for no condition, before any device is opened."""
    conditions = (
        *(Present(query) for query in parsed.shown),
        *(Gone(query) for query in parsed.gone),
        *(() if parsed.app is None else (Foreground(parsed.app),)),
        *((Settled(),) if parsed.settled else ()),
    )
    require_condition(conditions)
    return WaitCommand(conditions, parsed.timeout_ms)
