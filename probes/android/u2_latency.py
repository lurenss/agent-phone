import json
import statistics
import sys
import time

import uiautomator2 as u2

RUNS = int(sys.argv[1]) if len(sys.argv) > 1 else 7
label = sys.argv[2] if len(sys.argv) > 2 else "screen"

t = time.perf_counter()
d = u2.connect()
info = d.info
connect_ms = (time.perf_counter() - t) * 1000


def timed(fn):
    t = time.perf_counter()
    try:
        out = fn()
        return (time.perf_counter() - t) * 1000, True, out
    except Exception as e:
        return (time.perf_counter() - t) * 1000, False, repr(e)[:120]


rows = {"u2_dump": [], "u2_key_noop": []}
last = {}
for _ in range(RUNS):
    ms, ok, out = timed(lambda: d.dump_hierarchy())
    if ok:
        ok = "<hierarchy" in out
        last["u2_dump"] = f"nodes={out.count('<node')} bytes={len(out)}"
    else:
        last["u2_dump"] = out
    rows["u2_dump"].append((ms, ok))
    ms, ok, out = timed(lambda: d.jsonrpc.pressKeyCode(0))
    rows["u2_key_noop"].append((ms, ok))
    last["u2_key_noop"] = str(out)[:60]

print(
    json.dumps({"label": label, "connect_ms": round(connect_ms), "package": info.get("currentPackageName")})
)
for k, v in rows.items():
    ts = [m for m, _ in v]
    print(
        json.dumps(
            {
                "label": label,
                "probe": k,
                "runs": len(ts),
                "errors": sum(1 for _, ok in v if not ok),
                "median_ms": round(statistics.median(ts)),
                "min_ms": round(min(ts)),
                "max_ms": round(max(ts)),
                "last_note": last.get(k),
            }
        )
    )
