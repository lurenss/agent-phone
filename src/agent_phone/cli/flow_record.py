"""`agent-phone flow record TRACE --out FILE`: the draft of a flow, from what an agent did by hand.

TRACE is a device's trace of one day (`cli/trace.py`). Each command in it that sent input or
waited, and was ok, becomes a step with the words the agent typed. Three things change on the way,
so that the draft replays on another day:

- A target the agent named by ref becomes a query on the role and the name the ref resolved to,
  which the command's end line holds. A target with no name stays a ref, and the flow file refuses
  to load until someone names it another way.
- Typed text is `<N chars>` in a trace, and becomes a parameter. So a draft never holds it.
- The effects the agent granted become the draft's `grants`.

Looks (`snapshot`, `find`, `get`, `is`, `clipboard get`, `screenshot`), commands that failed or
died, and the lines of a flow's own run are left out. A line whose words no longer parse is left
out too and named in the envelope: a trace hides typed text wherever it stands, so a text of one
or two characters can change another word of its line. It reads one file and opens no device.
The draft is private like the trace, because it holds names from the screen.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from agent_phone.cli.batch import parse_step
from agent_phone.cli.commands import ScreenshotCommand
from agent_phone.cli.flow_args import FlowRecordCommand
from agent_phone.cli.trace import at, target_of
from agent_phone.core.commands.clipboard import ClipboardGetCommand
from agent_phone.core.commands.find import FindCommand
from agent_phone.core.commands.get import GetCommand
from agent_phone.core.commands.is_ import IsCommand
from agent_phone.core.commands.snapshot import SnapshotCommand
from agent_phone.core.envelope import VERSION
from agent_phone.core.outcome import ErrorCode, Refusal
from agent_phone.core.policy.mode import PermissionMode
from agent_phone.core.policy.rules import Effect
from agent_phone.core.query import Query
from agent_phone.core.refs.resolve import RefTarget
from agent_phone.core.role import Role

TYPED = re.compile(r"<\d+ chars>")
LOOKS = (SnapshotCommand, FindCommand, GetCommand, IsCommand, ClipboardGetCommand, ScreenshotCommand)
HEADER = "# A draft from `agent-phone flow record`. Read each step, then try it with --dry-run.\n"


@dataclass(frozen=True, slots=True)
class FlowDraft:
    """`refs` lists the steps that still name a ref, which a flow file may not. `skipped` lists
    the `seq` of each command that was ok and whose traced words do not parse."""

    out: Path
    mode: PermissionMode
    steps: int
    params: tuple[str, ...]
    refs: tuple[int, ...]
    skipped: tuple[int, ...]
    exit_code: int = 0

    def wire(self) -> dict[str, object]:
        return {
            "v": VERSION,
            "ok": True,
            "command": "flow record",
            "permission_mode": self.mode.value,
            "device": None,
            "data": {
                "out": str(self.out),
                "steps": self.steps,
                "params": list(self.params),
                "refs": list(self.refs),
                "skipped": list(self.skipped),
            },
        }


def record_flow(command: FlowRecordCommand, mode: PermissionMode) -> FlowDraft:
    lines = read_trace(command.trace)
    ends = {line.get("seq"): line for line in lines if line.get("line") == "end"}
    runs: list[list[str]] = []
    params: list[str] = []
    refs: list[int] = []
    skipped: list[int] = []
    grants: set[Effect] = set()
    for begin in lines:
        seq, argv = begin.get("seq"), begin.get("argv")
        end = ends.get(seq)
        if begin.get("line") != "begin" or "flow" in begin or end is None or end.get("ok") is not True:
            continue
        if not (
            isinstance(seq, int) and isinstance(argv, list) and argv and all(isinstance(w, str) for w in argv)
        ):
            raise not_a_trace(command.trace, "a begin line has no seq or no argv")
        typed = any(TYPED.search(word) for word in argv)
        name = f"text{len(params) + 1 if params else ''}"
        words = [TYPED.sub("{" + name + "}", word) for word in argv]
        try:
            parsed = parse_step(len(runs), tuple(words)).command
        except Refusal:
            skipped.append(seq)
            continue
        if isinstance(parsed, LOOKS):
            continue
        target = target_of(parsed)
        if isinstance(target, RefTarget):
            query = resolved(end)
            if query is None:
                refs.append(len(runs))
            else:
                words = [query if word == str(target.token) else word for word in words]
        if typed:
            params.append(name)
        grants |= getattr(parsed, "commit", frozenset())
        runs.append(words)
    if not runs:
        raise Refusal(
            ErrorCode.INVALID_ARGS,
            f"{command.trace} holds no input or wait that was ok, so there is nothing to replay.",
        )
    write(command.out, draft(command.out.stem, sorted(effect.value for effect in grants), params, runs))
    return FlowDraft(command.out, mode, len(runs), tuple(params), tuple(refs), tuple(skipped))


def read_trace(path: Path) -> list[Mapping[str, object]]:
    try:
        lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    except (OSError, ValueError) as error:
        raise not_a_trace(path, str(error)) from error
    if not all(isinstance(line, dict) for line in lines):
        raise not_a_trace(path, "a line is not an object")
    return lines


def not_a_trace(path: Path, problem: str) -> Refusal:
    return Refusal(
        ErrorCode.INVALID_ARGS,
        f"{path} is not a trace: {problem}. Pass a device's file of one day, "
        "<state root>/traces/<serial>/<UTC date>.jsonl.",
    )


def resolved(end: Mapping[str, object]) -> str | None:
    """The query for the element a ref resolved to, None when it had no name to be found by."""
    role, name = at(end, "target", "role"), at(end, "target", "name")
    if not (isinstance(name, str) and name and role in {member.value for member in Role}):
        return None
    return Query(name=name, role=Role(role)).describe()


def draft(name: str, grants: list[str], params: list[str], runs: list[list[str]]) -> str:
    """The flow file. A JSON string is a TOML basic string, so the words are written as JSON."""
    head = f"{HEADER}\n[flow]\nname = {words(name)}\ngrants = {words(grants)}\nparams = {words(params)}\n"
    return head + "".join(f"\n[[step]]\nrun = {words(run)}\n" for run in runs)


def words(value: str | list[str]) -> str:
    """JSON leaves U+007F as it is, and TOML takes it only escaped."""
    return json.dumps(value, ensure_ascii=False).replace("\x7f", "\\u007f")


def write(out: Path, text: str) -> None:
    try:
        with os.fdopen(
            os.open(out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w", encoding="utf-8"
        ) as file:
            file.write(text)
    except OSError as error:
        raise Refusal(
            ErrorCode.INVALID_ARGS,
            f"The draft cannot be written to {out}: {error}. A draft never replaces a file.",
        ) from error
