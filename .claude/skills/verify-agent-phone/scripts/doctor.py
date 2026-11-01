#!/usr/bin/env python3
"""Is this phone worth driving? Read-only. Run it from the repo root:

    uv run python -I .claude/skills/verify-agent-phone/scripts/doctor.py [--serial SERIAL]

Each line is `ok`, `note` or `stop`, then the check and what it found. The exit code is 1 when a
line says `stop`. It sends no input and starts nothing on the phone.
"""

import argparse
import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
CLI = Path(sys.executable).parent / "agent-phone"
FOREIGN_IDLE_S = 60
verdicts: list[str] = []


def say(verdict: str, check: str, found: str) -> None:
    verdicts.append(verdict)
    print(f"{verdict} {check}: {found}", flush=True)


def run(*argv: str) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("AGENT_PHONE_")}
    return subprocess.run(argv, capture_output=True, text=True, env=env, timeout=60)


def cli(*args: str) -> dict:
    done = run(str(CLI), *args)
    try:
        return json.loads(done.stdout)
    except ValueError:
        return {"ok": False, "error": {"code": "NO_ENVELOPE", "message": done.stdout + done.stderr}}


def shell(serial: str, script: str) -> str:
    return run("adb", "-s", serial, "shell", script).stdout


def checkout() -> None:
    head = run("git", "-C", str(REPO), "rev-parse", "--short", "HEAD").stdout.strip()
    changed = len(run("git", "-C", str(REPO), "status", "--short").stdout.splitlines())
    say("ok", "checkout", f"{REPO} at {head}, {changed} uncommitted paths, CLI {CLI}")
    listed = cli("skills", "list")
    if not listed.get("ok"):
        say("stop", "cli", f"the checkout's CLI does not run: {listed.get('error')}. Run `uv sync`.")


def device(wanted: str | None) -> str | None:
    rows = cli("devices")
    if not rows.get("ok"):
        say("stop", "devices", str(rows.get("error")))
        return None
    ready = [row for row in rows["data"]["devices"] if row["ready"]]
    chosen = [row for row in ready if wanted in (None, row["serial"])]
    if len(chosen) != 1:
        found = ", ".join(row["serial"] for row in rows["data"]["devices"]) or "none"
        say("stop", "device", f"need one ready device{f' {wanted}' if wanted else ''}, adb lists {found}")
        return None
    row = chosen[0]
    if "problem" in row:
        say("stop", "facts", f"{row['serial']} is ready but its facts fail: {row['problem']}")
        return None
    say("ok", "device", f"{row['serial']} {row['model']} api {row['api']} locale {row['locale']}")
    say("ok", "boot", row["boot_id"])
    return row["serial"]


def screen(serial: str) -> None:
    power = shell(serial, "dumpsys power")
    awake = "mWakefulness=Awake" in power
    say("ok" if awake else "stop", "screen", "awake" if awake else "not awake; waking the phone is an input")
    focus = [line.strip() for line in shell(serial, "dumpsys window").splitlines() if "mCurrentFocus" in line]
    say("ok", "focus", focus[0] if focus else "no window has focus")


def server(serial: str) -> None:
    status = cli("server", "status", "-d", serial)
    if not status.get("ok"):
        say("stop", "server", str(status.get("error")))
        return
    data = status["data"]
    if not data["running"]:
        say("ok", "server", "stopped; the run starts it, so cleanup stops it")
    elif not data["watchdog"]:
        say("stop", "server", "a uiautomator2 server without a watchdog runs: another tool owns the phone")
    elif data["idle_for_s"] is not None and data["idle_for_s"] < FOREIGN_IDLE_S:
        say("note", "server", f"running, used {data['idle_for_s']} s ago; if this run did not use it, wait")
    else:
        say("ok", "server", f"running with its watchdog, idle {data['idle_for_s']} s; leave it at cleanup")
    holders = shell(serial, "pidof uiautomator").split()
    if holders:
        say("stop", "uiautomation", f"a uiautomator process ({' '.join(holders)}) holds the phone")


def protected(serial: str) -> None:
    """Each package that the serial's profile in examples/devices protects must still run."""
    for path in sorted((REPO / "examples" / "devices").glob("*.toml")):
        profile = tomllib.loads(path.read_text(encoding="utf-8"))
        if profile.get("device", {}).get("serial") != serial:
            continue
        for entry in profile.get("protected", []):
            package = entry["package"]
            pattern = package.replace(".", "[.]")
            pids = shell(serial, f"pgrep -f '{pattern}'").split()
            found = f"running, pid {' '.join(pids)}" if pids else "not running; do not start or stop it"
            say("ok" if pids else "note", f"protected {package}", found)


def main() -> int:
    parser = argparse.ArgumentParser(prog="doctor.py")
    parser.add_argument("--serial", help="the device to check when several are ready")
    serial = None
    checkout()
    if "stop" not in verdicts:
        serial = device(parser.parse_args().serial)
    if serial is not None:
        screen(serial)
        server(serial)
        protected(serial)
    return 1 if "stop" in verdicts else 0


if __name__ == "__main__":
    sys.exit(main())
