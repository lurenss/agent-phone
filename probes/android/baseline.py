import json
import statistics
import subprocess
import sys
import time

RUNS = int(sys.argv[1]) if len(sys.argv) > 1 else 5


def adb(*args, out=False):
    t = time.perf_counter()
    p = subprocess.run(["adb", *args], capture_output=True, timeout=60)
    return time.perf_counter() - t, p


def floor():
    dt, p = adb("shell", "true")
    return dt, p.returncode == 0, ""


def dump_like_mbs():
    t = time.perf_counter()
    subprocess.run(["adb", "shell", "rm", "-f", "/sdcard/ap.xml"], capture_output=True)
    d = subprocess.run(
        ["adb", "shell", "uiautomator", "dump", "/sdcard/ap.xml"], capture_output=True, text=True
    )
    c = subprocess.run(["adb", "shell", "cat", "/sdcard/ap.xml"], capture_output=True, text=True)
    dt = time.perf_counter() - t
    ok = "<hierarchy" in c.stdout
    return dt, ok, f"nodes={c.stdout.count('<node')} bytes={len(c.stdout)} msg={d.stdout.strip()[:60]!r}"


def noop_input():
    dt, p = adb("shell", "input", "keyevent", "0")
    return dt, p.returncode == 0 and not p.stderr, p.stderr.decode()[:60]


def screencap():
    dt, p = adb("exec-out", "screencap", "-p")
    return dt, p.stdout[:4] == b"\x89PNG", f"bytes={len(p.stdout)}"


probes = {
    "adb_floor": floor,
    "uiautomator_dump_mbs": dump_like_mbs,
    "input_noop": noop_input,
    "screencap": screencap,
}
res = {k: [] for k in probes}
notes = {k: [] for k in probes}
for _ in range(RUNS):
    for name, fn in probes.items():
        dt, ok, note = fn()
        res[name].append((dt, ok))
        notes[name].append(note)

for name, rows in res.items():
    ts = [dt * 1000 for dt, ok in rows]
    errors = sum(1 for _, ok in rows if not ok)
    print(
        json.dumps(
            {
                "probe": name,
                "runs": len(ts),
                "errors": errors,
                "median_ms": round(statistics.median(ts)),
                "min_ms": round(min(ts)),
                "max_ms": round(max(ts)),
                "last_note": notes[name][-1],
            }
        )
    )
