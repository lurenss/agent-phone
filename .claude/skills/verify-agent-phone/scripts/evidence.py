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
is refused. The reads it knows without `--input` are agent-phone's read commands, adb's
`devices`, `dumpsys`, `getprop`, `logcat -d` and a few more, and `probes/android/raw_dump.py`. Every
other `python` needs `--input`.
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
REPO = Path(__file__).resolve().parents[4]
PROFILES = REPO / "examples" / "devices"
RAW_DUMP = REPO / "probes" / "android" / "raw_dump.py"
AGENT_PHONE_READS = {"devices", "snapshot", "find", "get", "is", "wait", "server", "skills", "screenshot"}
AGENT_PHONE_READ_PAIRS = {("clipboard", "get")}
ADB_READS = {"devices", "get-state", "get-serialno", "version"}
ADB_OPTIONS_WITH_VALUE = {"-s", "-t", "-H", "-P", "-L"}
SHELL_READS = set(
    "cat date dumpsys echo getprop grep head id ls pgrep pidof ps screencap stat tail wc".split()
)
SHELL_READ_PAIRS = {("settings", "get"), ("uiautomator", "dump")}
LOGCAT_CHANGES = {"-c", "-G", "-P", "-f", "--clear", "--buffer-size", "--prune", "--file"}
LOGCAT_BUFFERS = {"main", "system", "radio", "events", "crash", "kernel", "default"}
SERIAL_WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]*")
LABEL_WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
RECORD_KEYS = {"label", "argv", "input", "started_utc", "ms", "exit"}
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


def logcat_reads(words: list[str]) -> bool:
    """`logcat -d` prints the buffers and exits. It stays a read unless a flag clears a buffer (-c),
    resizes it (-G), sets the prune list (-P) or writes a file on the phone (-f), or a buffer other
    than the named ones is asked for, such as `-b all`. A short flag may be clustered, as `-dc`, so
    every letter counts."""
    flags, buffers = set(), []
    for at, word in enumerate(words):
        following = words[at + 1] if at + 1 < len(words) else ""
        if word.startswith("--"):
            name, _, value = word.partition("=")
            flags.add(name)
            if name == "--buffer":
                buffers.append(value or following)
        elif word.startswith("-") and word[1:2].isalpha():
            flags.update(f"-{letter}" for letter in word[1:])
            if "b" in word:
                buffers.append(word.partition("b")[2] or following)
    dumps = bool(flags & {"-d", "--dump"})
    return dumps and not flags & LOGCAT_CHANGES and all(set(b.split(",")) <= LOGCAT_BUFFERS for b in buffers)


def raw_dump_reads(words: list[str]) -> bool:
    """`probes/android/raw_dump.py SERIAL LABEL` holds the device lock, reads the screen through
    agent-phone's adapter and saves one file under `probes/android/raw/`. The label becomes part of
    that path, so it may not climb out of the folder."""
    if len(words) != 3 or not SERIAL_WORD.fullmatch(words[1]) or not LABEL_WORD.fullmatch(words[2]):
        return False
    return Path(words[0]).resolve() == RAW_DUMP


def is_read(argv: list[str]) -> bool:
    if argv[0] == "python":
        return raw_dump_reads(argv[1:])
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
    if rest[0] == "logcat":
        return logcat_reads(rest[1:])
    return rest[0] in ADB_READS


def batch_files(argv: list[str]) -> list[Path]:
    """The files that an `agent-phone batch` names, or [] for any other command. A batch keeps
    its steps in a file, so the argv alone does not say what it sends."""
    if argv[0] != "agent-phone":
        return []
    words = argv[1:]
    while words and words[0] in ("-d", "--device"):
        words = words[2:]
    if not words or words[0] != "batch":
        return []
    return [Path(word) for word in words[1:] if word != "-" and Path(word).is_file()]


def scanned(argv: list[str]) -> str:
    """The words an input is judged by for a protected package: its argv and the steps of a
    batch file, without the brackets and backslashes that hide a package name in JSON or a
    quoted script."""
    steps = [path.read_text(encoding="utf-8", errors="replace") for path in batch_files(argv)]
    return re.sub(r"[\[\]\\]", "", " ".join([*argv, *steps]))


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
    if args.input and argv[0] == "agent-phone" and "batch" in argv[1:] and not batch_files(argv):
        sys.exit("evidence: a batch input must name its steps file, so the record can show what it sends")
    plain = scanned(argv)
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
    found = (json.loads(path.read_text(encoding="utf-8")) for path in Path(run).glob("*.json"))
    entries = [entry for entry in found if isinstance(entry, dict) and RECORD_KEYS <= entry.keys()]
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
