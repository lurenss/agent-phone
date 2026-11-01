#!/usr/bin/env python3
"""The record of one verification run, kept under the state root and outside git, because it
holds what the phone's screen showed. Run it from the repo root:

    uv run python -I .claude/skills/verify-agent-phone/scripts/evidence.py new <feature>
    uv run python -I .claude/skills/verify-agent-phone/scripts/evidence.py run <run> <label> \\
        [--input] [--env NAME=VALUE]... [--out FILE] -- <command>...
    uv run python -I .claude/skills/verify-agent-phone/scripts/evidence.py list <run>

`run` drops every AGENT_PHONE_* variable, so the CLI runs its defaults as from a plain shell,
then adds the `--env` pairs. `agent-phone` and `python` mean this checkout's. A command that can
change the phone needs `--input`, and an input that names a package a device profile protects
is refused.
"""

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import time
import tomllib
from datetime import UTC, datetime
from pathlib import Path

from agent_phone.cli.settings import DEFAULT_STATE_ROOT

VERIFY_ROOT = DEFAULT_STATE_ROOT / "verify"
PROFILES = Path(__file__).resolve().parents[4] / "examples" / "devices"
AGENT_PHONE_READS = {"devices", "snapshot", "find", "get", "is", "server", "skills", "screenshot"}
AGENT_PHONE_READ_PAIRS = {("clipboard", "get")}
ADB_READS = {"devices", "get-state", "get-serialno", "version"}
ADB_OPTIONS_WITH_VALUE = {"-s", "-t", "-H", "-P", "-L"}
SHELL_READS = set(
    "cat date dumpsys echo getprop grep head id ls pgrep pidof ps screencap stat tail wc".split()
)
SHELL_READ_PAIRS = {("settings", "get"), ("uiautomator", "dump")}
SEPARATORS = re.compile(r"&&|\|\||[;\n|]|(?<![>&\d])&(?!>)")


def protected_packages() -> set[str]:
    return {
        entry["package"]
        for path in sorted(PROFILES.glob("*.toml"))
        for entry in tomllib.loads(path.read_text(encoding="utf-8")).get("protected", [])
    }


def shell_reads(script: list[str]) -> bool:
    """Every command of the script, split at `;`, `&&`, `||`, `|` and `&`, is a known read. The
    list is short on purpose: anything else counts as a change."""
    for command in SEPARATORS.split(" ".join(script)):
        try:
            words = shlex.split(command)
        except ValueError:
            return False
        if not words or (words[0] == "wm" and len(words) == 2):
            continue
        if words[0] not in SHELL_READS and tuple(words[:2]) not in SHELL_READ_PAIRS:
            return False
    return True


def is_read(argv: list[str]) -> bool:
    if argv[0] == "agent-phone":
        words = argv[1:]
        while words and words[0] in ("-d", "--device"):
            words = words[2:]
        return bool(words) and (words[0] in AGENT_PHONE_READS or tuple(words[:2]) in AGENT_PHONE_READ_PAIRS)
    if argv[0] != "adb":
        return False
    at = 1
    while at < len(argv) and argv[at].startswith("-"):
        at += 2 if argv[at] in ADB_OPTIONS_WITH_VALUE else 1
    rest = argv[at:]
    if not rest:
        return False
    if rest[0] in ("shell", "exec-out"):
        return shell_reads(rest[1:])
    return rest[0] in ADB_READS


def resolved(argv: list[str]) -> list[str]:
    here = Path(sys.executable).parent
    programs = {"agent-phone": str(here / "agent-phone"), "python": sys.executable}
    return [programs.get(argv[0], argv[0]), *argv[1:]]


def new(feature: str) -> int:
    DEFAULT_STATE_ROOT.mkdir(mode=0o700, exist_ok=True)
    VERIFY_ROOT.mkdir(mode=0o700, exist_ok=True)
    run = VERIFY_ROOT / f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{feature}"
    run.mkdir(mode=0o700)
    print(run)
    return 0


def record(args: argparse.Namespace) -> int:
    run, argv = Path(args.run), args.command
    target = run / f"{args.label}.json"
    if not run.is_dir() or target.exists():
        sys.exit(f"evidence: {target} exists or {run} is not a run folder; records are never overwritten")
    if not argv:
        sys.exit("evidence: give the command after --")
    if not args.input and not is_read(argv):
        sys.exit(f"evidence: {shlex.join(argv)} may change the phone. Pass --input if your task allows it.")
    plain = re.sub(r"[\[\]\\]", "", " ".join(argv))
    named = sorted(package for package in protected_packages() if package in plain)
    if args.input and named:
        sys.exit(f"evidence: refused, the input names the protected package {named}")
    extra = dict(pair.split("=", 1) for pair in args.env)
    env = {k: v for k, v in os.environ.items() if not k.startswith("AGENT_PHONE_")} | extra
    started = datetime.now(UTC).isoformat(timespec="milliseconds")
    clock = time.perf_counter()
    try:
        done = subprocess.run(resolved(argv), capture_output=True, env=env, timeout=args.timeout)
    except subprocess.TimeoutExpired as expired:
        done = subprocess.CompletedProcess(argv, 124, expired.stdout or b"", expired.stderr or b"")
    ms = round((time.perf_counter() - clock) * 1000)
    entry = {
        "label": args.label,
        "argv": argv,
        "env": extra,
        "input": args.input,
        "started_utc": started,
        "ms": ms,
        "exit": done.returncode,
        "stdout_bytes": len(done.stdout),
        "stderr": done.stderr.decode(errors="replace"),
    }
    if args.out:
        (run / args.out).write_bytes(done.stdout)
        entry["out"] = args.out
        print(run / args.out)
    else:
        text = done.stdout.decode(errors="replace")
        try:
            entry["stdout"] = json.loads(text)
        except ValueError:
            entry["stdout"] = text
        sys.stdout.write(text)
    target.write_text(json.dumps(entry, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return done.returncode


def listing(run: str) -> int:
    if not Path(run).is_dir():
        sys.exit(f"evidence: {run} is not a run folder")
    entries = [json.loads(path.read_text(encoding="utf-8")) for path in Path(run).glob("*.json")]
    entries.sort(key=lambda entry: entry["started_utc"])
    for entry in entries:
        kind = "input" if entry["input"] else "read"
        print(f"{entry['started_utc']} {entry['label']} {kind} exit={entry['exit']} {entry['ms']}ms")
        print(f"    {shlex.join(entry['argv'])}")
    inputs = [shlex.join(entry["argv"]) for entry in entries if entry["input"]]
    print(f"{len(entries)} records, {len(inputs)} inputs")
    for line in inputs:
        print(f"input: {line}")
    return 0


def main(argv: list[str]) -> int:
    """Everything after the first `--` is the command, so no flag of it is read as ours."""
    ours, command = (argv[: argv.index("--")], argv[argv.index("--") + 1 :]) if "--" in argv else (argv, [])
    parser = argparse.ArgumentParser(prog="evidence.py")
    actions = parser.add_subparsers(dest="action", required=True)
    actions.add_parser("new").add_argument("feature")
    run = actions.add_parser("run")
    run.add_argument("run")
    run.add_argument("label")
    run.add_argument("--input", action="store_true", help="the command may change the phone")
    run.add_argument("--env", action="append", default=[], metavar="NAME=VALUE")
    run.add_argument("--out", metavar="FILE", help="save stdout to this file in the run folder")
    run.add_argument("--timeout", type=float, default=120, help="seconds before the command is killed")
    actions.add_parser("list").add_argument("run")
    args = parser.parse_args(ours)
    match args.action:
        case "new":
            return new(args.feature)
        case "run":
            args.command = command
            return record(args)
        case "list":
            return listing(args.run)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
