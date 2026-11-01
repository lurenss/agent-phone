"""Command-line arguments of `batch`: only where its steps come from. A step is an argv array that
`parse_args` parses like any command line, so there is no second schema (`cli/batch.py`)."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class BatchCommand:
    """`source` None reads the steps from stdin."""

    source: Path | None


def add_batch(commands: argparse._SubParsersAction, after: argparse.ArgumentParser) -> None:
    batch = commands.add_parser(
        "batch",
        parents=[after],
        help="run several steps in one call and print one result with a trace",
        description="Read a JSON array of steps from FILE, or from stdin when FILE is - or missing. A "
        'step is an array of the arguments of one command without agent-phone, such as ["click", '
        '"name=Display", "--wait-for", "name*=Brightness"]. The steps run in order under one device '
        "lock and stop at the first step that is not ok. Give -d here and not in a step, and give "
        "--commit and --policy in the step they serve. The result holds each step's own envelope "
        "and the path of a JSONL trace.",
    )
    batch.add_argument("file", nargs="?", metavar="FILE", help="a JSON file of steps; - or no FILE is stdin")


def batch_command(parsed: argparse.Namespace) -> BatchCommand:
    return BatchCommand(None if parsed.file in (None, "-") else Path(parsed.file))
