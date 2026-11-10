#!/usr/bin/env python3
"""Measure how fast and how cheaply a fresh agent drives a phone step by step with agent-phone.

    python3 probes/agent_bench/run.py run <label> [--runs 3] [--checkout PATH] [--serial emulator-5566]
    python3 probes/agent_bench/run.py table [<label>...]

One run: reset the emulator (Settings stopped, its search history cleared, dark theme off, the
stock device name, the home screen), start a fresh headless `claude -p --model sonnet` with
`task.md`, and let it drive the emulator through `ap.py`, which logs every call. Then read the
emulator with adb, not through the agent, to decide whether the task ended correctly. A run that
ended wrong is a failed run, and `table` leaves it out of the medians and counts it.

The agent may run only the wrapper and read files: every other command is denied, so it cannot
reach adb or another device. `--checkout` names the agent-phone checkout under test (its
`.venv/bin/agent-phone` and its shipped guide), so two checkouts can be measured in turn.

Results go to `~/.agent-phone/bench/<label>/run-<n>/`, outside git, because the logs hold what the
screen showed: `calls.jsonl` (one line per call), `stream.jsonl` (the agent's session) and
`result.json` (the metrics).

Metrics: `wall_s` the agent's whole session, `calls` wrapper calls, `tool_s` seconds inside
agent-phone, `out_bytes` bytes it printed, `turns` model turns, `tokens` every token the session
processed (input, cache writes, cache reads and output over all turns), `context` the tokens of the
last turn's prompt, `cost_usd` the session's list price, `timeouts` calls that ended in TIMEOUT.
In a log from before the wrapper wrote each call's error code, they are the failed calls that took
more than 4.5 s.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
BENCH_ROOT = Path.home() / ".agent-phone" / "bench"
EMULATOR = re.compile(r"emulator-\d+")
STOCK_NAME = "sdk_gphone64_arm64"
WANTED_NAME = "bench-phone"
SETTINGS = "com.android.settings"
SEARCH = "com.google.android.settings.intelligence"
MAIN_PAGE = "com.android.settings/com.android.settings.Settings}"
AGENT_TIMEOUT_S = 900
METRICS = ("wall_s", "calls", "tool_s", "out_bytes", "turns", "tokens", "context", "cost_usd", "timeouts")


def adb(serial: str, *words: str) -> str:
    done = subprocess.run(["adb", "-s", serial, *words], capture_output=True, text=True, timeout=60)
    return done.stdout.strip()


def reset(serial: str, exe: Path, env: dict[str, str]) -> None:
    for package in (SETTINGS, SEARCH):
        adb(serial, "shell", "am", "force-stop", package)
    adb(serial, "shell", "pm", "clear", SEARCH)
    adb(serial, "shell", "cmd", "uimode", "night", "no")
    adb(serial, "shell", "settings", "put", "global", "device_name", STOCK_NAME)
    adb(serial, "shell", "input", "keyevent", "KEYCODE_HOME")
    subprocess.run([str(exe), "-d", serial, "server", "start"], capture_output=True, env=env, timeout=60)
    time.sleep(2)


def verify(serial: str, report: dict | None) -> list[str]:
    """What is wrong with the end state, read from the emulator and not from the agent."""
    wrong = []
    if "yes" not in adb(serial, "shell", "cmd", "uimode", "night"):
        wrong.append("dark theme is off")
    if adb(serial, "shell", "settings", "get", "global", "device_name") != WANTED_NAME:
        wrong.append("the device name is not bench-phone")
    focus = [
        line for line in adb(serial, "shell", "dumpsys", "window").splitlines() if "mCurrentFocus" in line
    ]
    if not any(MAIN_PAGE in line for line in focus):
        wrong.append(f"the focus is not the main page of Settings: {' '.join(focus).strip()[:120]}")
    if report is None:
        return [*wrong, "the final message is not the report"]
    if report.get("result") != "ok":
        wrong.append(f"the agent reported {str(report.get('result'))[:120]!r}")
    if str(report.get("android_version")) != adb(serial, "shell", "getprop", "ro.build.version.release"):
        wrong.append("the reported Android version is wrong")
    addresses = set(re.findall(r"inet (\d+\.\d+\.\d+\.\d+)", adb(serial, "shell", "ip", "-4", "addr")))
    if str(report.get("ip_address")) not in addresses - {"127.0.0.1"}:
        wrong.append("the reported IP address is wrong")
    return wrong


def report_of(text: str) -> dict | None:
    found = re.findall(r"\{[^{}]*\"result\"[^{}]*\}", text)
    try:
        return json.loads(found[-1]) if found else None
    except ValueError:
        return None


def run_agent(folder: Path, checkout: Path, serial: str) -> dict:
    exe = checkout / ".venv" / "bin" / "agent-phone"
    wrapper = f"python3 {HERE / 'ap.py'}"
    guide = checkout / "src" / "agent_phone" / "skills" / "agent-phone" / "SKILL.md"
    prompt = (
        (HERE / "task.md").read_text(encoding="utf-8").replace("{ap}", wrapper).replace("{guide}", str(guide))
    )
    env = {k: v for k, v in os.environ.items() if not k.startswith("AGENT_PHONE_")}
    env |= {
        "AGENT_PHONE_HOME": str(BENCH_ROOT / "home"),
        "AP_BENCH_SERIAL": serial,
        "AP_BENCH_BIN": str(exe),
        "AP_BENCH_LOG": str(folder / "calls.jsonl"),
    }
    reset(serial, exe, env)
    cwd = folder / "cwd"
    cwd.mkdir()
    command = [
        *("claude", "-p", prompt, "--model", "sonnet", "--safe-mode", "--strict-mcp-config"),
        *("--tools", "Bash,Read", "--allowedTools", "Read", f"Bash({wrapper} *)"),
        *("--output-format", "stream-json", "--verbose", "--no-session-persistence"),
    ]
    started = time.time()
    with (folder / "stream.jsonl").open("w", encoding="utf-8") as stream:
        try:
            subprocess.run(
                command, stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT, cwd=cwd, env=env,
                timeout=AGENT_TIMEOUT_S, check=False,
            )  # fmt: skip
        except subprocess.TimeoutExpired:
            pass  # no result line was written, so the run has no report and counts as failed
    wall = time.time() - started
    wrong = verify(serial, final_report(folder))
    return measure(folder, wall) | {"wrong": [*api_error(folder), *wrong]}


def events(folder: Path) -> list[dict]:
    lines = (folder / "stream.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.startswith("{")]


def api_error(folder: Path) -> list[str]:
    """A session that the model API cut off, such as on a usage limit, says nothing about the tool."""
    result = next((e for e in events(folder) if e.get("type") == "result"), {})
    return (
        [f"the agent's session ended on an API error: {result['api_error']}"]
        if result.get("api_error")
        else []
    )


def final_report(folder: Path) -> dict | None:
    result = next((e for e in events(folder) if e.get("type") == "result"), {})
    return report_of(str(result.get("result", "")))


def measure(folder: Path, wall: float) -> dict:
    log = folder / "calls.jsonl"
    calls = (
        [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []
    )
    stream = events(folder)
    result = next((e for e in stream if e.get("type") == "result"), {})
    usage = result.get("usage", {})
    turns = [
        e["message"]["usage"] for e in stream if e.get("type") == "assistant" and "usage" in e["message"]
    ]
    sides = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
    denied = len(result.get("permission_denials", []))
    return {
        "wall_s": round(wall, 1),
        "calls": len(calls),
        "tool_s": round(sum(c["s"] for c in calls), 1),
        "out_bytes": sum(c["out_bytes"] for c in calls),
        "turns": result.get("num_turns"),
        "tokens": sum(usage.get(side, 0) for side in (*sides, "output_tokens")),
        "output_tokens": usage.get("output_tokens"),
        "context": sum(turns[-1].get(side, 0) for side in sides) if turns else None,
        "cost_usd": round(result.get("total_cost_usd", 0), 4),
        "timeouts": sum(1 for c in calls if timed_out(c)),
        "failed_calls": sum(1 for c in calls if c["exit"] != 0),
        "denied": denied,
    }


def timed_out(call: dict) -> bool:
    if "code" in call:
        return call["code"] == "TIMEOUT"
    return call["exit"] == 1 and call["s"] > 4.5


def run(args: argparse.Namespace) -> int:
    if not EMULATOR.fullmatch(args.serial):
        sys.exit("run.py: the benchmark runs only on an emulator serial such as emulator-5566")
    checkout = Path(args.checkout).resolve()
    head = subprocess.run(
        ["git", "-C", str(checkout), "rev-parse", "--short", "HEAD"], capture_output=True, text=True
    )
    dirty = subprocess.run(
        ["git", "-C", str(checkout), "status", "--porcelain", "src"], capture_output=True, text=True
    )
    base = BENCH_ROOT / args.label
    for _ in range(args.runs):
        number = 1 + len(list(base.glob("run-*")))
        folder = base / f"run-{number}"
        folder.mkdir(parents=True, mode=0o700)
        result = run_agent(folder, checkout, args.serial)
        result |= {
            "label": args.label,
            "run": number,
            "head": head.stdout.strip(),
            "dirty": bool(dirty.stdout.strip()),
        }
        (folder / "result.json").write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
        print(json.dumps(result), flush=True)
    return table(argparse.Namespace(labels=[args.label]))


def table(args: argparse.Namespace) -> int:
    labels = args.labels or sorted(p.name for p in BENCH_ROOT.iterdir() if any(p.glob("run-*/result.json")))
    print("| label | runs ok/all | " + " | ".join(METRICS) + " |")
    print("|---|---|" + "---|" * len(METRICS))
    for label in labels:
        results = [json.loads(p.read_text()) for p in sorted((BENCH_ROOT / label).glob("run-*/result.json"))]
        good = [r for r in results if not r["wrong"]]
        cells = []
        for metric in METRICS:
            values = [r[metric] for r in good if r[metric] is not None]
            if not values:
                cells.append("-")
                continue
            middle = statistics.median(values)
            cells.append(f"{middle:g} ({min(values):g} to {max(values):g})")
        print(f"| {label} | {len(good)}/{len(results)} | " + " | ".join(cells) + " |")
        for bad in (r for r in results if r["wrong"]):
            print(f"  failed run {bad['run']}: {'; '.join(bad['wrong'])}")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="run.py", description=__doc__.splitlines()[0])
    actions = parser.add_subparsers(dest="action", required=True)
    one = actions.add_parser("run", help="run the task with a fresh agent and print the metrics")
    one.add_argument("label")
    one.add_argument("--runs", type=int, default=3)
    one.add_argument("--checkout", default=str(REPO))
    one.add_argument("--serial", default="emulator-5566")
    many = actions.add_parser("table", help="print the median and the range of each label")
    many.add_argument("labels", nargs="*")
    args = parser.parse_args(argv)
    return run(args) if args.action == "run" else table(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
