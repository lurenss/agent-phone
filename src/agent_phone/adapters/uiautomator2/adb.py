"""The adb command line. Arguments go to `subprocess` as a list and never through a shell string
on the computer. What runs on the phone is the script text that callers pass to `shell`.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from agent_phone.core.device import Connected, Serial
from agent_phone.core.outcome import ErrorCode, Refusal

DEFAULT_TIMEOUT_S = 15.0


@dataclass(frozen=True, slots=True)
class AdbResult:
    status: int
    stdout: str
    stderr: str


class Adb(Protocol):
    def run(self, args: Sequence[str], timeout_s: float = DEFAULT_TIMEOUT_S) -> AdbResult: ...


class SubprocessAdb:
    """`ADB` in the environment names the binary, as it does for other adb tools."""

    def __init__(self, binary: str | None = None) -> None:
        self._binary = binary or os.environ.get("ADB", "adb")

    def run(self, args: Sequence[str], timeout_s: float = DEFAULT_TIMEOUT_S) -> AdbResult:
        try:
            done = subprocess.run(
                [self._binary, *args],
                capture_output=True,
                text=True,
                errors="replace",
                stdin=subprocess.DEVNULL,
                timeout=timeout_s,
            )
        except FileNotFoundError as error:
            raise Refusal(
                ErrorCode.TRANSPORT, f"adb is not installed, or {self._binary!r} is not on PATH."
            ) from error
        except subprocess.TimeoutExpired as error:
            raise Refusal(
                ErrorCode.TRANSPORT, f"adb {' '.join(args[:3])} did not finish within {timeout_s:g} s."
            ) from error
        return AdbResult(done.returncode, done.stdout, done.stderr)


def shell(adb: Adb, serial: Serial, script: str, timeout_s: float = DEFAULT_TIMEOUT_S) -> AdbResult:
    return adb.run(("-s", serial, "shell", script), timeout_s)


def first_line(text: str) -> str:
    lines = text.strip().splitlines()
    return lines[0] if lines else ""


def parse_devices(output: str) -> tuple[Connected, ...]:
    """Rows of `adb devices -l`. Only the state `device` is ready. Anything after the header is
    a row, so the daemon's start-up banner, which comes before it, is ignored."""
    lines = output.splitlines()
    try:
        rows = lines[lines.index("List of devices attached") + 1 :]
    except ValueError as error:
        raise Refusal(ErrorCode.TRANSPORT, f"adb devices answered {output.strip()[:120]!r}.") from error
    found = []
    for row in rows:
        fields = row.split()
        if len(fields) < 2:
            continue
        model = next((field.removeprefix("model:") for field in fields[2:] if field.startswith("model:")), "")
        found.append(Connected(Serial(fields[0]), model, ready=fields[1] == "device"))
    return tuple(found)
