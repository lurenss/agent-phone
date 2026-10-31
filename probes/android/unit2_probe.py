"""Live checks for unit 2 (devices, server lifetime, lock). Run from the repo root:

    uv run python -I probes/android/unit2_probe.py facts
    uv run python -I probes/android/unit2_probe.py watchdog
    uv run python -I probes/android/unit2_probe.py accessibility
    uv run python -I probes/android/unit2_probe.py quirks

Each subcommand prints one JSON line per result. They read the phone and start and stop the
uiautomator2 server. They send no input, launch no app and touch no package.
"""

import json
import statistics
import subprocess
import sys
import time
import urllib.request

ADB = "adb"
SERVER = "pgrep -f 'uia2[.]Main'"
WATCHDOG = "pgrep -f 'ap-watchdo[g]'"
STOP = "pkill -f 'uia2[.]Main'; for p in $(pgrep -f 'ap-watchdo[g]'); do kill -9 $p; done; rm -f "
LASTUSE = "/data/local/tmp/ap-lastuse"
SEQUENTIAL = (
    "echo sdk=$(getprop ro.build.version.sdk); echo abi=$(getprop ro.product.cpu.abi); "
    "echo model=$(getprop ro.product.model); echo loc=$(getprop persist.sys.locale); "
    "echo boot=$(cat /proc/sys/kernel/random/boot_id); echo size=$(wm size); "
    "echo density=$(wm density); echo ime=$(settings get secure default_input_method)"
)
PARALLEL = (
    '(getprop | grep -E "^\\[(ro.build.version.sdk|ro.product.cpu.abi|ro.product.model|'
    'persist.sys.locale|ro.product.locale)\\]") & (echo "boot=$(cat /proc/sys/kernel/random/boot_id)") & '
    '(echo "size=$(wm size)") & (echo "density=$(wm density)") & '
    '(echo "ime=$(settings get secure default_input_method)") & wait'
)
WATCHDOG_BODY = f"""srv=$1; limit=$2; f={LASTUSE}
while grep -q "uia2[.]Main" /proc/$srv/cmdline 2>/dev/null; do
  age=$(( $(date +%s) - $(stat -c %Y $f 2>/dev/null || echo 0) ))
  if [ $age -ge $limit ]; then kill $srv; break; fi
  left=$((limit - age)); [ $left -gt 10 ] && left=10
  sleep $left
done"""


def adb(*args):
    return subprocess.run([ADB, *args], capture_output=True, text=True, timeout=30)


def serial():
    rows = [line.split() for line in adb("devices").stdout.splitlines()[1:] if line.strip()]
    ready = [row[0] for row in rows if row[1] == "device"]
    assert len(ready) == 1, f"expected one ready device, found {ready}"
    return ready[0]


def shell(device, script):
    return adb("-s", device, "shell", script).stdout


def timed_shell(device, script):
    start = time.perf_counter()
    out = shell(device, script)
    return (time.perf_counter() - start) * 1000, out


def emit(**row):
    print(json.dumps(row), flush=True)


def facts():
    device = serial()
    samples = {"sequential": [], "parallel": []}
    outputs = {}
    for _ in range(12):
        for name, script in (("sequential", SEQUENTIAL), ("parallel", PARALLEL)):
            ms, outputs[name] = timed_shell(device, script)
            samples[name].append(ms)
    for name, values in samples.items():
        emit(
            check="facts_round_trip",
            variant=name,
            runs=len(values),
            median_ms=round(statistics.median(values)),
            min_ms=round(min(values)),
            max_ms=round(max(values)),
            lines=len(outputs[name].strip().splitlines()),
        )
    emit(
        check="noop_shell",
        median_ms=round(statistics.median(timed_shell(device, "true")[0] for _ in range(12))),
    )
    ps = shell(device, "getprop persist.sys.locale; getprop ro.product.locale").split()
    emit(
        check="locale_props",
        persist_sys_locale=ps[0] if ps else "",
        ro_product_locale=ps[1] if len(ps) > 1 else "",
    )


def ping(port):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/ping", timeout=1) as reply:
            return reply.status == 200
    except OSError:
        return False


def start_detached(device, limit):
    script = (
        f"touch {LASTUSE}\n"
        "CLASSPATH=/data/local/tmp/u2.jar nohup app_process / com.wetest.uia2.Main -p 9008 "
        "</dev/null >/dev/null 2>&1 &\n"
        "srv=$!\n"
        f"nohup sh -c '{WATCHDOG_BODY}' ap-watchdog $srv {limit} </dev/null >/dev/null 2>&1 &\n"
        "echo $srv"
    )
    return int(shell(device, script).strip())


def alive(device):
    return bool(shell(device, SERVER).strip()), bool(shell(device, WATCHDOG).strip())


def wait_until(check, deadline_s):
    start = time.monotonic()
    while time.monotonic() - start < deadline_s:
        if check():
            return time.monotonic() - start
        time.sleep(0.25)
    return None


def watchdog():
    device = serial()
    limit = 6
    port = adb("-s", device, "forward", "tcp:0", "tcp:9008").stdout.strip()
    try:
        shell(device, "pkill -f 'uia2[.]Main'")
        pid = start_detached(device, limit)
        up = wait_until(lambda: ping(port), 10)
        server, dog = alive(device)
        emit(check="detached_start", pid=pid, ping_after_s=up and round(up, 1), server=server, watchdog=dog)

        for _ in range(5):
            time.sleep(limit / 2)
            shell(device, f"touch {LASTUSE}")
        server, dog = alive(device)
        emit(check="touched_server_survives", seconds=round(5 * limit / 2), server=server, watchdog=dog)

        shell(device, f"touch {LASTUSE}")
        start = time.monotonic()
        gone = wait_until(lambda: not alive(device)[0], limit * 3)
        server, dog = alive(device)
        emit(
            check="idle_server_stops",
            limit_s=limit,
            gone_after_s=gone and round(gone, 1),
            measured_from_last_touch=True,
            server=server,
            watchdog=dog,
            waited_s=round(time.monotonic() - start, 1),
        )
    finally:
        shell(device, STOP + LASTUSE)
        adb("-s", device, "forward", "--remove", f"tcp:{port}")
        emit(check="cleanup", server_left=bool(shell(device, SERVER).strip()))


def accessibility():
    device = serial()
    flag = "settings get secure accessibility_enabled"
    port = adb("-s", device, "forward", "tcp:0", "tcp:9008").stdout.strip()
    try:
        shell(device, "pkill -f 'uia2[.]Main'")
        before = shell(device, flag).strip()
        start_detached(device, 600)
        up = wait_until(lambda: ping(port), 10)
        during = shell(device, flag).strip()
        shell(device, "pkill -f 'uia2[.]Main'")
        wait_until(lambda: not alive(device)[0], 10)
        after = shell(device, flag).strip()
        emit(
            check="accessibility_enabled",
            before=before,
            during=during,
            after=after,
            ping_after_s=up and round(up, 1),
        )
    finally:
        shell(device, STOP + LASTUSE)
        adb("-s", device, "forward", "--remove", f"tcp:{port}")


def shell_result(device, script):
    done = adb("-s", device, "shell", script)
    return {"adb_exit": done.returncode, "stdout": done.stdout.split()}


def quirks():
    device = serial()
    try:
        shell(device, STOP + LASTUSE)
        emit(check="pgrep_plain_pattern", **shell_result(device, "pgrep -f uia2.Main; echo done"))
        emit(check="pgrep_bracket_pattern", **shell_result(device, "pgrep -f 'uia2[.]Main'; echo rc=$?"))
        emit(check="pkill_plain_pattern", **shell_result(device, "pkill -f uia2.Main; echo done"))
        emit(check="pkill_no_signal", **shell_result(device, "pkill -f 'zzz[z]'; echo rc=$?"))
        for option in ("-9", "-KILL"):
            emit(
                check=f"pkill_signal_{option}",
                **shell_result(device, f"pkill {option} -f 'zzz[z]'; echo rc=$?"),
            )

        start_detached(device, 600)
        time.sleep(1)
        term = shell_result(device, "pkill -f 'ap-watchdo[g]'; echo rc=$?")
        gone = wait_until(lambda: not alive(device)[1], 15)
        emit(
            check="sigterm_to_watchdog",
            pkill=term["stdout"],
            gone_after_s=gone and round(gone, 1),
            waited_s=15,
        )
        shell(device, "for p in $(pgrep -f 'ap-watchdo[g]'); do kill -9 $p; done")
        emit(check="kill_9_watchdog", watchdog_left=alive(device)[1])
    finally:
        shell(device, STOP + LASTUSE)


if __name__ == "__main__":
    {"facts": facts, "watchdog": watchdog, "accessibility": accessibility, "quirks": quirks}[sys.argv[1]]()
