import json
import statistics
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

import uiautomator2 as u2

label = sys.argv[1]


def sh(cmd):
    return subprocess.run(["adb", "shell", cmd], capture_output=True, text=True)


def server_alive():
    return "uia2.Main" in sh("ps -A -o ARGS").stdout


def stop_server():
    sh("pkill -f uia2.Main")
    while server_alive():
        time.sleep(0.2)


def start_server():
    d = u2.connect()
    d.jsonrpc.deviceInfo()
    return d


def old_dump():
    t = time.perf_counter()
    sh("rm -f /sdcard/ap.xml")
    msg = sh("uiautomator dump /sdcard/ap.xml").stdout.strip()
    raw = sh("cat /sdcard/ap.xml").stdout
    return (time.perf_counter() - t) * 1000, "<hierarchy" in raw, raw, msg


def u2_dump(d):
    t = time.perf_counter()
    try:
        raw = d.dump_hierarchy()
        return (time.perf_counter() - t) * 1000, "<hierarchy" in raw, raw, ""
    except Exception as e:
        return (time.perf_counter() - t) * 1000, False, "", repr(e)[:80]


def snapshot_bytes(raw):
    rows = []
    for n in ET.fromstring(raw[raw.index("<hierarchy") :]).iter("node"):
        a = n.attrib
        acts = [k for k in ("clickable", "long-clickable", "scrollable", "checkable") if a.get(k) == "true"]
        if a.get("class", "").endswith("EditText"):
            acts.append("editable")
        text = a.get("text") or a.get("content-desc")
        if not acts and not text:
            continue
        row = {
            "ref": f"@s1:e{len(rows) + 1}" if acts else None,
            "role": a.get("class", "").rsplit(".", 1)[-1],
            "acts": acts or None,
            "name": (text or "")[:80] or None,
            "id": a.get("resource-id", "").split("/")[-1] or None,
            "b": a.get("bounds"),
        }
        rows.append({k: v for k, v in row.items() if v})
    return (
        len("\n".join(json.dumps(r, separators=(",", ":")) for r in rows)),
        len(rows),
        sum(1 for r in rows if "ref" in r),
    )


samples = {"old": [], "u2": []}
last_raw = ""
for _ in range(2):
    stop_server()
    for _ in range(3):
        ms, ok, raw, msg = old_dump()
        samples["old"].append({"ms": round(ms), "ok": ok, "nodes": raw.count("<node"), "msg": msg[:40]})
    d = start_server()
    for _ in range(5):
        ms, ok, raw, msg = u2_dump(d)
        samples["u2"].append({"ms": round(ms), "ok": ok, "nodes": raw.count("<node"), "msg": msg})
        if ok:
            last_raw = raw
stop_server()

for side, rows in samples.items():
    good = [r["ms"] for r in rows if r["ok"]]
    print(
        json.dumps(
            {
                "label": label,
                "side": side,
                "runs": len(rows),
                "errors": sum(not r["ok"] for r in rows),
                "median_ms": round(statistics.median(good)) if good else None,
                "min_ms": min(good) if good else None,
                "max_ms": max(good) if good else None,
                "nodes": sorted({r["nodes"] for r in rows}),
                "fail_msgs": sorted({r["msg"] for r in rows if not r["ok"]}),
            }
        )
    )
b, n, refs = snapshot_bytes(last_raw)
print(
    json.dumps(
        {"label": label, "realistic_snapshot_bytes": b, "rows": n, "refs": refs, "raw_bytes": len(last_raw)}
    )
)
