"""Traces: JSONL files that say what each command did and whether its input went out.

    <state root>/traces/<serial>/<UTC date>.jsonl                 one per device and day
    <state root>/traces/<serial>/<UTC timestamp>-batch.jsonl      one per batch

Both have mode 0600, in a folder of mode 0700, because the screen's words can be private. The
day's file takes a begin line before each command that reads or drives the phone and an end line
after it, so a begin line with no end line is a command that died on the way. A batch's file has
one line per step that ran and a last line that ends it. A line is appended and flushed as it is
written, so a crash leaves the lines before it. No line holds the `after` snapshot or a tree, and
none holds the text a command typed.
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
BEGIN = '{"line":"begin"'


class Trace:
    def __init__(self, path: Path, file: TextIO, begun: int = 0) -> None:
        self.path = path
        self._file = file
        self._begun = begun

    @classmethod
    def open(cls, state_root: Path, serial: Serial) -> Trace:
        """A new file for one batch, created closed to other users. A name that is taken is never
        reused."""
        folder = closed_folder(state_root, serial)
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

    @classmethod
    def daily(cls, state_root: Path, serial: Serial) -> Trace:
        """The device's file of this UTC day, which every command of the day appends to. The
        caller holds the device lock, so two commands never write it at once."""
        path = closed_folder(state_root, serial) / f"{datetime.now(UTC):%Y-%m-%d}.jsonl"
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_APPEND, 0o600)
        os.fchmod(fd, 0o600)
        file = os.fdopen(fd, "a+", encoding="utf-8")
        file.seek(0)
        return cls(path, file, sum(line.startswith(BEGIN) for line in file))

    def begin(self, command: str, argv: Sequence[str], **more: object) -> int:
        """Write the begin line of one command and return its `seq`, which its end line repeats.
        `argv` is written as given, so the caller hides typed text first (`redacted`)."""
        seq = self._begun
        self._begun += 1
        self.append(
            {"line": "begin", "seq": seq, "command": command, "argv": list(argv), "started_utc": utc_now()}
            | more
        )
        return seq

    def end(self, seq: int, command: object, envelope: Mapping[str, object], ms: int) -> None:
        self.append(
            {"line": "end", "seq": seq, "permission_mode": envelope["permission_mode"], "ms": ms}
            | result_record(command, envelope)
        )

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
    its value (`--wait-for=value=hunter2`) keeps its name and loses the text in its value. A word
    that is the text itself is hidden whole, also when it starts with `-` and stood after `--`."""
    match command:
        case SetTextCommand(text=text):
            keep = 1
        case ClipboardSetCommand(text=text):
            keep = 2
        case _:
            return list(argv)
    shown = f"<{len(text)} chars>"

    def hide(word: str) -> str:
        if word == text:
            return shown
        if not text:
            return word
        if word.startswith("-"):
            name, equals, value = word.partition("=")
            return name + equals + value.replace(text, shown)
        return word.replace(text, shown)

    return [word if at < keep else hide(word) for at, word in enumerate(argv)]


def closed_folder(state_root: Path, serial: Serial) -> Path:
    """`traces/<serial>` under the state root, both closed to other users, also when they exist
    with wider rights."""
    folder = state_root / "traces" / serial
    folder.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    for directory in (folder.parent, folder):
        directory.mkdir(mode=0o700, exist_ok=True)
        directory.chmod(0o700)
    return folder


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def without_device(argv: Sequence[str], serial: Serial | None) -> list[str]:
    """`argv` without the flag that named `serial`, so it starts at the command as a batch step
    does. The trace's folder already names the device."""
    words = list(argv)
    for at, word in enumerate(words):
        flag, equals, value = word.partition("=")
        if flag != "-d" and not (len(flag) > 2 and "--device".startswith(flag)):
            continue
        if not equals and words[at + 1 : at + 2] == [serial]:
            return words[:at] + words[at + 2 :]
        if equals and value == serial:
            return words[:at] + words[at + 1 :]
    return [word for word in words if word != f"-d{serial}"]


def step_record(
    index: int,
    argv: Sequence[str],
    command: object,
    started_utc: str,
    ms: int,
    envelope: Mapping[str, object],
) -> dict[str, object]:
    return {
        "line": "step",
        "i": index,
        "argv": redacted(argv, command),
        "permission_mode": envelope["permission_mode"],
        "started_utc": started_utc,
        "ms": ms,
    } | result_record(command, envelope)


def result_record(command: object, envelope: Mapping[str, object]) -> dict[str, object]:
    """What a command did, read from the envelope it printed so the two cannot disagree. The input,
    target and gate are set only for an input that went out. A target that was refused still shows
    the ref or query that was asked for."""
    reported = at(envelope, "data", "target")
    return {
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
