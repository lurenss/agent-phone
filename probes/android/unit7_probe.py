"""Done-when 4 of docs/plan.md on a second device: the snapshot suite of done-when 1 on stock
Settings and a system dialog. Run from the repo root with a run folder from the verify skill:

    RUN=$(uv run python -I .claude/skills/verify-agent-phone/scripts/evidence.py new thor-bench)
    uv run python -I probes/android/unit7_probe.py "$RUN" <serial>

Every call goes through the verify skill's `evidence.py`, which records it in the run folder, and
the only inputs are the ones in INPUTS: Settings by intent, the system's Bluetooth discoverable
request (it only asks, and BACK declines it), BACK and HOME. It prints one JSON line per check.
"""

import json
import statistics
import subprocess
import sys
from pathlib import Path

EVIDENCE = [sys.executable, "-I", ".claude/skills/verify-agent-phone/scripts/evidence.py"]
SETTINGS = "intent:#Intent;action=android.settings.SETTINGS;end"
DISCOVERABLE = "intent:#Intent;action=android.bluetooth.adapter.action.REQUEST_DISCOVERABLE;end"
INPUTS = {
    "open-settings": ["open-url", SETTINGS],
    "open-dialog": ["open-url", DISCOVERABLE],
    "back": ["press", "back"],
    "home": ["press", "home"],
}
RUNS, SETTLES, BUDGET, DIALOG_READS = 20, 10, 8 * 1024, 10
labels: set[str] = set()
sent: list[str] = []


def run(folder: Path, serial: str, label: str, *args: str, is_input: bool = False) -> dict:
    """One agent-phone call through evidence.py. Returns its record."""
    assert label not in labels, label
    labels.add(label)
    flag = ["--input"] if is_input else []
    command = [*EVIDENCE, "run", str(folder), label, *flag, "--", "agent-phone", "-d", serial, *args]
    subprocess.run(command, capture_output=True, text=True, timeout=120)
    return json.loads((folder / f"{label}.json").read_text())


def send(folder: Path, serial: str, name: str, step: int) -> dict:
    sent.append(" ".join(INPUTS[name]))
    return run(folder, serial, f"{name}-{step}", *INPUTS[name], is_input=True)


def focus(folder: Path, serial: str) -> str | None:
    """Display 0's focused window, from `dumpsys window displays`: a read agent-phone did not make,
    recorded by evidence.py like every other call."""
    label = f"focus-{len([x for x in labels if x.startswith('focus-')])}"
    labels.add(label)
    command = [
        *EVIDENCE,
        "run",
        str(folder),
        label,
        "--",
        "adb",
        "-s",
        serial,
        "shell",
        "dumpsys window displays",
    ]
    subprocess.run(command, capture_output=True, text=True, timeout=60)
    out = json.loads((folder / f"{label}.json").read_text()).get("stdout") or ""
    current = None
    for line in str(out).splitlines():
        line = line.strip()
        if line.startswith("Display: mDisplayId="):
            current = line.removeprefix("Display: mDisplayId=").split()[0]
        elif line.startswith("mCurrentFocus=") and current == "0":
            return line.split("u0 ", 1)[-1].rstrip("}")
    return None


def emit(**row: object) -> None:
    print(json.dumps(row), flush=True)


def envelope(record: dict) -> dict:
    stdout = record.get("stdout")
    return stdout if isinstance(stdout, dict) else {}


def bench(folder: Path, serial: str, label: str, dialog: bool) -> None:
    times, sizes, lines, wrong, errors = [], [], [], 0, 0
    for i in range(RUNS):
        record = run(folder, serial, f"{label}-snap-{i}", "snapshot")
        wire = envelope(record)
        data = wire.get("data") or {}
        errors += wire.get("ok") is not True
        wrong += not (data.get("app") == "com.android.settings" and data.get("dialog") is dialog)
        times.append(record["ms"])
        sizes.append(record["stdout_bytes"])
        lines.append(len(data.get("tree", [])))
    settle_times, settled = [], 0
    for i in range(SETTLES):
        record = run(folder, serial, f"{label}-settle-{i}", "snapshot", "--settle")
        settle_times.append(record["ms"])
        settled += (envelope(record).get("data") or {}).get("settled") == "settled"
    emit(
        check="warm_snapshot",
        screen=label,
        runs=RUNS,
        errors=errors,
        wrong_screen=wrong,
        median_ms=round(statistics.median(times)),
        range_ms=[min(times), max(times)],
        bytes=[min(sizes), max(sizes)],
        under_8_kb=max(sizes) < BUDGET,
        tree_lines=[min(lines), max(lines)],
    )
    emit(
        check="warm_settle",
        screen=label,
        settled=settled,
        runs=SETTLES,
        median_ms=round(statistics.median(settle_times)),
    )


def main() -> None:
    folder, serial = Path(sys.argv[1]), sys.argv[2]
    send(folder, serial, "home", 0)
    run(folder, serial, "home-wait", "wait", "--app", "com.android.launcher3", "--timeout-ms", "5000")
    opened = send(folder, serial, "open-settings", 0)
    fresh = envelope(run(folder, serial, "fresh-settle", "snapshot", "--settle")).get("data") or {}
    emit(
        check="fresh_after_open",
        delivery=envelope(opened).get("delivery"),
        app=fresh.get("app"),
        settled=fresh.get("settled"),
        dialog=fresh.get("dialog"),
        first_lines=fresh.get("tree", [])[:3],
        focus=focus(folder, serial),
    )
    bench(folder, serial, "settings", dialog=False)
    send(folder, serial, "open-dialog", 0)
    shown: dict = {}
    for attempt in range(DIALOG_READS):
        record = run(folder, serial, f"dialog-wait-{attempt}", "snapshot", "--settle")
        shown = envelope(record).get("data") or {}
        if shown.get("dialog") is True:
            break
    emit(
        check="dialog_shown",
        reads=attempt + 1,
        dialog=shown.get("dialog"),
        lines=shown.get("tree"),
        focus=focus(folder, serial),
    )
    if shown.get("dialog") is True:
        bench(folder, serial, "dialog", dialog=True)
        surface = envelope(run(folder, serial, "dialog-surface", "snapshot", "--surface", "dialog"))
        emit(check="surface_dialog", ok=surface.get("ok"), lines=(surface.get("data") or {}).get("tree"))
    send(folder, serial, "back", 0)
    after = envelope(run(folder, serial, "after-back", "snapshot", "--settle")).get("data") or {}
    emit(
        check="dialog_dismissed",
        dialog=after.get("dialog"),
        app=after.get("app"),
        focus=focus(folder, serial),
    )
    send(folder, serial, "home", 1)
    emit(check="inputs", sent=sent)


if __name__ == "__main__":
    main()
