#!/usr/bin/env python3
"""Boot and stop an Android emulator to bring up a device with no live accounts. Run it from the repo
root:

    uv run python -I .claude/skills/port-android-device/scripts/emulator.py boot \\
        --avd NAME --locale LL-CC [--port 5554]
    uv run python -I .claude/skills/port-android-device/scripts/emulator.py stop --serial emulator-5554

This is the one script of the skill that runs `adb` itself and not through the verify skill's
`evidence.py`. An emulator has no live accounts, so booting it is not an input to a phone, and
`evidence.py` could not record the start of a process on the computer anyway. Every script that
touches a device after that still goes through `evidence.py`.

`boot` starts `$ANDROID_HOME/emulator/emulator -avd NAME -no-window -no-audio -no-boot-anim
-no-snapshot -change-locale LL-CC -port PORT` detached, with its log in `<state root>/emulators/`, and
prints the serial, `emulator-PORT`, when the emulator is booted. `ANDROID_HOME` defaults to
`~/Library/Android/sdk` and `adb` is the one on `PATH`. The emulator refuses an SDK root with no
`platform-tools` folder ("Broken AVD system path"), so `boot` checks for it and says how to make it.
It never makes the folder itself.

Booted means all three of these on one poll: `sys.boot_completed` is 1, `persist.sys.locale` is the
requested locale, and `dumpsys window` names a focus that is not `FallbackHome`. With a locale to
apply, the emulator reports `sys.boot_completed` about 30 s in, then restarts the framework: for a
while `dumpsys window` says "Can't find service: window", and the focus is Settings' FallbackHome
until the launcher comes up. `stop` runs `adb -s SERIAL emu kill`.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import IO

from agent_phone.cli.settings import Settings
from agent_phone.core.wait.clock import Clock, SystemClock
from agent_phone.core.wait.until import until

BOOT_DEADLINE_S = 240
POLL_GAP_S = 3.0
DEFAULT_PORT = 5554
LOCALE = re.compile(r"[a-z]{2,3}-[A-Z]{2}")
SERIAL = re.compile(r"emulator-\d+")
FOCUS = re.compile(r"mCurrentFocus=(.*)")
Run = Callable[..., subprocess.CompletedProcess]
Start = Callable[[list[str], Path], "subprocess.Popen[bytes]"]


class BootFailed(RuntimeError):
    """The emulator process ended before it booted."""


def sdk_root(env: dict[str, str]) -> Path:
    return Path(env.get("ANDROID_HOME") or Path.home() / "Library" / "Android" / "sdk")


def boot_command(sdk: Path, avd: str, locale: str, port: int) -> list[str]:
    return [
        str(sdk / "emulator" / "emulator"),
        *("-avd", avd),
        *("-no-window", "-no-audio", "-no-boot-anim", "-no-snapshot"),
        *("-change-locale", locale),
        *("-port", str(port)),
    ]


def check_sdk(sdk: Path) -> None:
    """Exit with the fix when the SDK cannot start an emulator. Nothing is created."""
    if not (sdk / "emulator" / "emulator").is_file():
        sys.exit(f"emulator: there is no emulator at {sdk}/emulator/emulator. Set ANDROID_HOME to your SDK.")
    if not (sdk / "platform-tools").is_dir():
        sys.exit(
            f"emulator: {sdk}/platform-tools is missing, and the emulator refuses an SDK root without it "
            '("Broken AVD system path"). Make the folder and link your adb into it, then boot again:\n'
            f'  mkdir -p {sdk}/platform-tools && ln -s "$(command -v adb)" {sdk}/platform-tools/adb\n'
            "This script does not make it."
        )


def window_ready(dumpsys_window: str) -> bool:
    """A focus that names a window and is not FallbackHome. While the framework restarts the dump says
    "Can't find service: window" and has no focus line, and right after it the focus is null."""
    focus = [line.strip() for line in FOCUS.findall(dumpsys_window) if line.strip() != "null"]
    return bool(focus) and not any("FallbackHome" in line for line in focus)


def booted(run: Run, serial: str, locale: str | None) -> bool:
    """The three conditions, on one poll. A read that fails counts as not booted yet."""

    def read(*words: str) -> str:
        done = run(["adb", "-s", serial, "shell", *words], capture_output=True, text=True, timeout=60)
        return done.stdout.strip() if done.returncode == 0 else ""

    if read("getprop", "sys.boot_completed") != "1":
        return False
    if locale and read("getprop", "persist.sys.locale").replace("_", "-") != locale:
        return False
    return window_ready(read("dumpsys", "window"))


def running(run: Run, serial: str) -> bool:
    done = run(["adb", "-s", serial, "get-state"], capture_output=True, text=True, timeout=30)
    return done.returncode == 0 and done.stdout.strip() == "device"


def start(command: list[str], log: Path) -> subprocess.Popen[bytes]:
    """Detached: its own session, no stdin, and its output in the log."""
    log.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with log.open("wb") as out:
        return subprocess.Popen(
            command, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT, start_new_session=True
        )


def tail(log: Path, lines: int = 8) -> str:
    try:
        return "\n".join(log.read_text(errors="replace").splitlines()[-lines:])
    except OSError:
        return ""


def boot(
    args: argparse.Namespace, run: Run, launch: Start, clock: Clock, out: IO[str], env: dict[str, str]
) -> int:
    sdk, serial = sdk_root(env), f"emulator-{args.port}"
    check_sdk(sdk)
    if running(run, serial):
        sys.exit(f"emulator: {serial} is running already. Stop it first: emulator.py stop --serial {serial}")
    log = Settings.from_environment(env).state_root / "emulators" / f"{args.avd}-{args.port}.log"
    process = launch(boot_command(sdk, args.avd, args.locale, args.port), log)

    def attempt() -> bool | None:
        if (code := process.poll()) is not None:
            raise BootFailed(f"the emulator exited with code {code}. The end of its log, {log}:\n{tail(log)}")
        return True if booted(run, serial, args.locale) else None

    try:
        ready = until(clock, attempt, args.deadline_s, POLL_GAP_S)
    except BootFailed as failed:
        sys.exit(f"emulator: {failed}")
    if ready is None:
        sys.exit(
            f"emulator: {serial} did not finish booting within {args.deadline_s} s. It is still running. "
            f"Its log is {log}. Stop it with: emulator.py stop --serial {serial}"
        )
    print(serial, file=out)
    return 0


def stop(args: argparse.Namespace, run: Run, out: IO[str]) -> int:
    done = run(["adb", "-s", args.serial, "emu", "kill"], capture_output=True, text=True, timeout=60)
    print((done.stdout + done.stderr).strip(), file=out)
    return done.returncode


def serial_arg(text: str) -> str:
    if not SERIAL.fullmatch(text):
        raise argparse.ArgumentTypeError(f"{text!r} is not an emulator serial such as emulator-5554")
    return text


def locale_arg(text: str) -> str:
    if not LOCALE.fullmatch(text):
        raise argparse.ArgumentTypeError(f"{text!r} is not a locale such as it-IT or en-US")
    return text


def port_arg(text: str) -> int:
    if not text.isdigit() or not 5554 <= int(text) <= 5584 or int(text) % 2:
        raise argparse.ArgumentTypeError(f"{text!r} is not an even port from 5554 to 5584")
    return int(text)


def main(
    argv: list[str],
    run: Run = subprocess.run,
    launch: Start = start,
    clock: Clock | None = None,
    out: IO[str] = sys.stdout,
    env: dict[str, str] | None = None,
) -> int:
    parser = argparse.ArgumentParser(prog="emulator.py", description="Boot and stop a test emulator.")
    actions = parser.add_subparsers(dest="action", required=True)
    up = actions.add_parser("boot", help="start an emulator and wait until it is booted")
    up.add_argument("--avd", required=True)
    up.add_argument("--locale", required=True, type=locale_arg, metavar="LL-CC")
    up.add_argument("--port", type=port_arg, default=DEFAULT_PORT)
    up.add_argument("--deadline-s", type=int, default=BOOT_DEADLINE_S, help="seconds to wait for the boot")
    down = actions.add_parser("stop", help="kill an emulator")
    down.add_argument("--serial", required=True, type=serial_arg)
    args = parser.parse_args(argv)
    if args.action == "stop":
        return stop(args, run, out)
    return boot(args, run, launch, clock or SystemClock(), out, dict(os.environ) if env is None else env)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
