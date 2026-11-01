"""The one way the port scripts reach a phone: through the verify skill's `evidence.py`, which
records every call in the run folder. A script that talks to a phone builds a `Recorder`.

A read goes through `adb`, `read` and `raw_dump`, and an input only through `send`. `send` looks
at the screen first when no read has happened since the last input, because agent-phone refuses
an input without a fresh observation (`OBSERVE_FIRST`). Nothing here calls adb itself.
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
EVIDENCE = [
    sys.executable,
    "-I",
    str(REPO / ".claude" / "skills" / "verify-agent-phone" / "scripts" / "evidence.py"),
]
RAW_DUMP = "probes/android/raw_dump.py"
NAME = re.compile(r"[a-z][a-z0-9-]*")
OBSERVING = {"snapshot", "wait", "find"}
LOOKS = 3
Runner = Callable[..., subprocess.CompletedProcess]


class EvidenceRefused(RuntimeError):
    """evidence.py wrote no record, so the call never ran. Its reason is on stderr."""


class ObserveFailed(RuntimeError):
    """No read of the screen succeeded, so no input may go out."""


@dataclass(frozen=True, slots=True, eq=False)
class Call:
    """One evidence record: the command's exit code, its time and what it printed."""

    record: dict

    @property
    def ms(self) -> int:
        return self.record["ms"]

    @property
    def stdout_bytes(self) -> int:
        return self.record.get("stdout_bytes", 0)

    @property
    def text(self) -> str:
        """evidence.py parses stdout as JSON when it can, so `0` or `null` come back as values."""
        out = self.record.get("stdout")
        return out if isinstance(out, str) else json.dumps(out)

    @property
    def envelope(self) -> dict:
        out = self.record.get("stdout")
        return out if isinstance(out, dict) else {}

    @property
    def ok(self) -> bool:
        return self.envelope.get("ok") is True

    @property
    def data(self) -> dict:
        return self.envelope.get("data") or {}

    @property
    def error_code(self) -> str | None:
        return (self.envelope.get("error") or {}).get("code")

    @property
    def delivery(self) -> str | None:
        return self.envelope.get("delivery")

    @property
    def verified_by(self) -> str | None:
        return self.data.get("verified_by")


@dataclass(eq=False)
class Recorder:
    run: Path
    serial: str
    runner: Runner = subprocess.run
    sent: list[str] = field(default_factory=list)
    fresh: bool = False
    used: set[str] = field(default_factory=set)

    def label(self, base: str) -> str:
        """A label evidence.py has not used in this run. It never overwrites a record, so a script
        that runs twice in one run folder gets `-2`, `-3` and so on."""
        label, n = base, 1
        while label in self.used or (self.run / f"{label}.json").exists():
            n += 1
            label = f"{base}-{n}"
        self.used.add(label)
        return label

    def call(self, label: str, argv: list[str], is_input: bool = False, timeout_s: int = 120) -> Call:
        label = self.label(label)
        flag = ["--input"] if is_input else []
        command = [*EVIDENCE, "run", str(self.run), label, *flag, "--timeout", str(timeout_s), "--", *argv]
        done = self.runner(command, capture_output=True, text=True, timeout=timeout_s + 30)
        target = self.run / f"{label}.json"
        if not target.is_file():
            raise EvidenceRefused(f"{shlex.join(argv)}: {(done.stderr or done.stdout).strip()}")
        if is_input:
            self.sent.append(shlex.join(argv))
            self.fresh = False
        return Call(json.loads(target.read_text()))

    def adb(self, label: str, *args: str) -> Call:
        return self.call(label, ["adb", "-s", self.serial, *args])

    def raw_dump(self, label: str, name: str) -> Call:
        """Save `probes/android/raw/<name>.raw.xml`, through the read evidence.py knows."""
        return self.call(label, ["python", RAW_DUMP, self.serial, name])

    def read(self, label: str, *args: str, timeout_s: int = 120) -> Call:
        call = self.call(label, ["agent-phone", "-d", self.serial, *args], timeout_s=timeout_s)
        if call.ok and args[0] in OBSERVING:
            self.fresh = True
        return call

    def look(self, label: str) -> Call:
        """A settled read, tried up to `LOOKS` times: a read can fail while the screen changes."""
        call = self.read(f"{label}-look", "snapshot", "--settle")
        for _ in range(LOOKS - 1):
            if call.ok:
                break
            call = self.read(f"{label}-look", "snapshot", "--settle")
        if not call.ok:
            raise ObserveFailed(f"no read of the screen worked: {call.error_code}")
        return call

    def send(self, label: str, *args: str) -> Call:
        """An input, after a read if none has happened since the last input."""
        if not self.fresh:
            self.look(label)
        return self.call(label, ["agent-phone", "-d", self.serial, *args], is_input=True)


class Journal:
    """`survey.jsonl` and its like: one JSON line per check, written and printed as it happens."""

    def __init__(self, path: Path) -> None:
        self.path = path
        path.write_text("")

    def emit(self, **row: object) -> None:
        line = json.dumps(row, ensure_ascii=False)
        print(line, flush=True)
        with self.path.open("a", encoding="utf-8") as out:
            out.write(line + "\n")


def run_folder(text: str) -> Path:
    path = Path(text)
    if not path.is_dir():
        raise argparse.ArgumentTypeError(f"{text} is not a run folder. Make one with evidence.py new.")
    return path


def device_name(text: str) -> str:
    if not NAME.fullmatch(text):
        raise argparse.ArgumentTypeError(
            f"{text!r} is not a device name: lowercase letters, digits and hyphens, starting with a letter."
        )
    return text
