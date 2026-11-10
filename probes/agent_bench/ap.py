#!/usr/bin/env python3
"""The benchmark's wrapper around one agent-phone command: it picks the emulator, runs the command
and appends one line to the call log (start time, arguments, seconds, bytes printed, exit code).

    AP_BENCH_SERIAL=emulator-5566 AP_BENCH_BIN=<checkout>/.venv/bin/agent-phone \\
        AP_BENCH_LOG=<run folder>/calls.jsonl python3 ap.py <agent-phone arguments>

It runs only against an emulator serial. It refuses `devices`, `server` and every word that starts
with `-d` or `--d`: the CLI takes `-d` again after the command, in any spelling argparse accepts
(`-dSERIAL`, `--device=SERIAL`, `--dev SERIAL`), and the later one wins, so one such word would
point the call at another phone. `devices` reads facts from every phone adb lists. A benchmark
never reaches a phone with live accounts.
"""

import json
import os
import re
import subprocess
import sys
import time

EMULATOR = re.compile(r"emulator-\d+")
REFUSED_COMMANDS = {"devices", "server"}
DEVICE_WORD = re.compile(r"-d|--d")
ARG_LOG_CHARS = 120


def main(argv: list[str]) -> int:
    serial, exe, log = (
        os.environ.get(name, "") for name in ("AP_BENCH_SERIAL", "AP_BENCH_BIN", "AP_BENCH_LOG")
    )
    if not EMULATOR.fullmatch(serial) or not exe or not log:
        sys.exit("ap.py: set AP_BENCH_SERIAL to an emulator serial, AP_BENCH_BIN and AP_BENCH_LOG")
    refused = sorted({word for word in argv if word in REFUSED_COMMANDS or DEVICE_WORD.match(word)})
    started = time.time()
    if refused:
        out = json.dumps({"ok": False, "error": {"code": "BENCH_REFUSED", "message": f"The benchmark "
                          f"wrapper picks the device. Leave out {', '.join(refused)}."}}) + "\n"  # fmt: skip
        code, err = 2, ""
    else:
        env = {
            k: v for k, v in os.environ.items() if not k.startswith("AGENT_PHONE_") or k == "AGENT_PHONE_HOME"
        }
        done = subprocess.run([exe, "-d", serial, *argv], capture_output=True, env=env)
        out, err, code = (
            done.stdout.decode(errors="replace"),
            done.stderr.decode(errors="replace"),
            done.returncode,
        )
    line = {
        "t": round(started, 3),
        "argv": [a if len(a) <= ARG_LOG_CHARS else a[:ARG_LOG_CHARS] + "…" for a in argv],
        "s": round(time.time() - started, 3),
        "out_bytes": len(out.encode()) + len(err.encode()),
        "exit": code,
        "code": error_code(out),
    }
    with open(log, "a", encoding="utf-8") as calls:
        calls.write(json.dumps(line, ensure_ascii=False) + "\n")
    sys.stdout.write(out)
    sys.stderr.write(err)
    return code


def error_code(out: str) -> str | None:
    try:
        return json.loads(out)["error"]["code"]
    except (ValueError, KeyError, TypeError):
        return None


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
