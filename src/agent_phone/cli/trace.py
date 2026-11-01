"""The trace of one batch: a JSONL file with one line per step that ran and a last line that ends it.

    <state root>/traces/<serial>/<UTC timestamp>-batch.jsonl      mode 0600, in a folder of mode 0700

A line is appended and flushed as its step ends, so a crash leaves the steps before it. The
file says what each step did and whether its input went out. It never holds the `after`
snapshot or a tree, because the step's envelope in the batch result has them, and it never holds
the text a step typed. The screen's words can be private, so the folder is closed to other users.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Self, TextIO

from agent_phone.core.commands.click import ClickCommand
from agent_phone.core.commands.clipboard import ClipboardSetCommand
from agent_phone.core.commands.scroll import ScrollCommand
from agent_phone.core.commands.set_text import SetTextCommand
from agent_phone.core.device import Serial
from agent_phone.core.envelope import encode
from agent_phone.core.refs.resolve import QueryTarget, RefTarget, Target

ATTEMPTS = 100


class Trace:
    def __init__(self, path: Path, file: TextIO) -> None:
        self.path = path
        self._file = file

    @classmethod
    def open(cls, state_root: Path, serial: Serial) -> Trace:
        """A new file, created closed to other users. A name that is taken is never reused."""
        folder = state_root / "traces" / serial
        folder.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        for directory in (folder.parent, folder):
            directory.mkdir(mode=0o700, exist_ok=True)
            directory.chmod(0o700)
        for _ in range(ATTEMPTS):
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
            path = folder / f"{stamp}-batch.jsonl"
            try:
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_APPEND, 0o600)
            except FileExistsError:
                continue
            os.fchmod(fd, 0o600)
            return cls(path, os.fdopen(fd, "a", encoding="utf-8"))
        raise FileExistsError(f"every name {folder}/<time>-batch.jsonl was taken")

    def append(self, record: Mapping[str, object]) -> None:
        self._file.write(encode(record) + "\n")
        self._file.flush()

    def close(self) -> None:
        self._file.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def redacted(argv: Sequence[str], command: object) -> list[str]:
    """`argv` with the text that `set-text` or `clipboard set` typed shown as `<N chars>`, wherever
    it stands, also inside a longer word such as the query `value=hunter2`. The command's own words
    and the flag names stay, because a flag name holds no text a caller typed. A flag written with
    its value (`--wait-for=value=hunter2`) keeps its name and loses the text in its value."""
    match command:
        case SetTextCommand(text=text):
            keep = 1
        case ClipboardSetCommand(text=text):
            keep = 2
        case _:
            return list(argv)
    shown = f"<{len(text)} chars>"

    def hide(word: str) -> str:
        if not text:
            return shown if word == text else word
        if word.startswith("-"):
            name, equals, value = word.partition("=")
            return name + equals + value.replace(text, shown)
        return word.replace(text, shown)

    return [word if at < keep else hide(word) for at, word in enumerate(argv)]


def step_record(
    index: int,
    argv: Sequence[str],
    command: object,
    started_utc: str,
    ms: int,
    envelope: Mapping[str, object],
) -> dict[str, object]:
    """What a step did, read from the envelope it printed so the two cannot disagree. The input,
    target and gate are set only for an input that went out. A target that was refused still shows
    the ref or query that was asked for."""
    reported = at(envelope, "data", "target")
    return {
        "line": "step",
        "i": index,
        "argv": redacted(argv, command),
        "mode": envelope["mode"],
        "started_utc": started_utc,
        "ms": ms,
        "ok": envelope["ok"],
        "delivery": envelope.get("delivery"),
        "retry": envelope.get("retry"),
        "error": at(envelope, "error", "code"),
        "input": at(envelope, "data", "input", "kind"),
        "target": target_record(command, reported),
        "gate": at(envelope, "data", "gate"),
    }


def end_record(stopped_at: int | None, ms: int) -> dict[str, object]:
    return {"line": "end", "stopped_at": stopped_at, "ms": ms}


def target_record(command: object, reported: object) -> dict[str, object] | None:
    """The ref or the query a step named, with the role and name it resolved to when it did."""
    target = target_of(command)
    if target is None:
        return None
    return {
        "ref": str(target.token) if isinstance(target, RefTarget) else None,
        "query": target.query.describe() if isinstance(target, QueryTarget) else None,
        "role": at(reported, "role"),
        "name": at(reported, "name"),
    }


def target_of(command: object) -> Target | None:
    match command:
        case ClickCommand(target=target) | SetTextCommand(target=target) | ScrollCommand(target=target):
            return target
        case _:
            return None


def at(wire: object, *path: str) -> object:
    for key in path:
        if not isinstance(wire, Mapping):
            return None
        wire = wire.get(key)
    return wire
