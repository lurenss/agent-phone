"""Live checks for unit 2 (devices, server lifetime, lock). Run from the repo root:

    uv run python -I probes/android/unit2_probe.py facts
    uv run python -I probes/android/unit2_probe.py watchdog
    uv run python -I probes/android/unit2_probe.py accessibility
    uv run python -I probes/android/unit2_probe.py quirks
    uv run python -I probes/android/unit2_probe.py bench
    uv run python -I probes/android/unit2_probe.py devices
    uv run python -I probes/android/unit2_probe.py idle
    uv run python -I probes/android/unit2_probe.py idle-default
    uv run python -I probes/android/unit2_probe.py concurrent
    uv run python -I probes/android/unit2_probe.py stop
    uv run python -I probes/android/unit2_probe.py foreign

Each subcommand prints one JSON line per result. They read the phone and start and stop the
uiautomator2 server. They send no input, launch no app and touch no package.
"""

import io
import json
import os
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

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


def wait_until(check, deadline_s, gap_s=0.25):
    start = time.monotonic()
    while time.monotonic() - start < deadline_s:
        if check():
            return time.monotonic() - start
        time.sleep(gap_s)
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


CLI = str(Path(sys.executable).parent / "agent-phone")


def run_cli(env, *args):
    """One CLI process, timed from spawn to exit. Returns (ms, exit code, envelope or None)."""
    start = time.perf_counter()
    done = subprocess.run([CLI, *args], capture_output=True, text=True, env=env, timeout=60)
    ms = (time.perf_counter() - start) * 1000
    try:
        wire = json.loads(done.stdout)
    except ValueError:
        wire = None
    return ms, done.returncode, wire


def summary(values):
    return {
        "runs": len(values),
        "median_ms": round(statistics.median(values)),
        "min_ms": round(min(values)),
        "max_ms": round(max(values)),
    }


def process_floor(env):
    """What a Python process costs before agent-phone does anything: bare start-up, then the
    imports the CLI makes."""
    python = sys.executable
    bare = [timed_run([python, "-I", "-c", "pass"], env) for _ in range(15)]
    imports = [timed_run([python, "-I", "-c", "import agent_phone.cli.process"], env) for _ in range(15)]
    return summary(bare), summary(imports)


def timed_run(argv, env):
    start = time.perf_counter()
    subprocess.run(argv, capture_output=True, env=env, check=True)
    return (time.perf_counter() - start) * 1000


def phases(env):
    """Where one run of the CLI's own code spends its time, from timers around each adb call,
    the server calls and the capture. It runs in a process of its own, as the CLI does, and
    apart from the timed runs, because the timers are part of what they measure."""
    from agent_phone.adapters.uiautomator2 import rpc
    from agent_phone.adapters.uiautomator2.adb import SubprocessAdb
    from agent_phone.adapters.uiautomator2.phone import U2Hub
    from agent_phone.cli import process
    from agent_phone.cli.settings import Settings
    from agent_phone.core.commands import snapshot

    spans = {}

    def timed(name, call):
        def wrapper(*args, **kwargs):
            start = time.perf_counter()
            try:
                return call(*args, **kwargs)
            finally:
                spans.setdefault(name, []).append((time.perf_counter() - start) * 1000)

        return wrapper

    class TimedAdb(SubprocessAdb):
        def run(self, args, timeout_s=15.0):
            name = {"devices": "adb devices", "forward": "adb forward (open and remove)"}.get(
                args[0] if args[0] != "-s" else args[2]
            )
            return timed(name or "adb shell (facts)", super().run)(args, timeout_s)

    rpc.JsonRpc.call = timed("dump rpc", rpc.JsonRpc.call)
    rpc.JsonRpc.ping = timed("ping", rpc.JsonRpc.ping)
    snapshot.capture = timed("capture and store", snapshot.capture)
    os.environ.update(env)
    settings = Settings.from_environment()
    hub = U2Hub(TimedAdb(), settings.idle_limit_s)
    start = time.perf_counter()
    process.run(["snapshot"], hub, settings, io.StringIO())
    total = (time.perf_counter() - start) * 1000
    return {name: round(sum(values), 1) for name, values in spans.items()} | {"run_total": round(total, 1)}


def phases_fresh(env, repeats=7):
    runs = []
    for _ in range(repeats):
        done = subprocess.run(
            [sys.executable, "-I", __file__, "phases-once"],
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
        )
        runs.append(json.loads(done.stdout))
    return {name: round(statistics.median(run[name] for run in runs), 1) for name in runs[0]}


def bench():
    device = serial()
    home = tempfile.mkdtemp(prefix="agent-phone-bench-")
    env = {**os.environ, "AGENT_PHONE_HOME": home}
    emit(
        check="host_load",
        loadavg=os.getloadavg(),
        cores=os.cpu_count(),
        phone_uptime=shell(device, "uptime").strip(),
    )
    try:
        run_cli(env, "server", "stop")
        cold_ms, code, wire = run_cli(env, "snapshot")
        emit(check="cold_first_snapshot", ms=round(cold_ms), exit=code, ok=bool(wire and wire["ok"]))
        warm, errors, sizes, packages = [], 0, set(), set()
        for _ in range(20):
            ms, code, wire = run_cli(env, "snapshot")
            ok = bool(wire and wire["ok"] and code == 0)
            errors += not ok
            warm.append(ms)
            if ok:
                sizes.add(len(json.dumps(wire, separators=(",", ":"), ensure_ascii=False).encode()))
                packages.add(wire["data"]["app"])
        emit(
            check="warm_snapshot",
            errors=errors,
            bytes=[min(sizes), max(sizes)],
            apps=len(packages),
            **summary(warm),
        )
        bare, imports = process_floor(env)
        emit(check="python_bare_start", **bare)
        emit(check="python_import_cli", **imports)
        emit(check="phases_fresh_process", runs=7, **phases_fresh(env))
    finally:
        run_cli(env, "server", "stop")
        emit(check="server_left", running=bool(shell(device, SERVER).strip()))


def fresh_env(**extra):
    return {**os.environ, "AGENT_PHONE_HOME": tempfile.mkdtemp(prefix="agent-phone-probe-"), **extra}


def devices():
    device = serial()
    ms, code, wire = run_cli(fresh_env(), "devices")
    row = next(row for row in wire["data"]["devices"] if row["serial"] == device)
    raw = {
        "model": shell(device, "getprop ro.product.model").strip(),
        "api": int(shell(device, "getprop ro.build.version.sdk")),
        "abi": shell(device, "getprop ro.product.cpu.abi").strip(),
        "display": [int(n) for n in shell(device, "wm size").split()[-1].split("x")],
        "density": int(shell(device, "wm density").split()[-1]),
        "locale": shell(device, "getprop persist.sys.locale").strip(),
        "ime": shell(device, "settings get secure default_input_method").strip().split("/")[0],
        "boot_id": shell(device, "cat /proc/sys/kernel/random/boot_id").strip(),
    }
    emit(
        check="devices_facts",
        ms=round(ms),
        exit=code,
        differing=[key for key in raw if row[key] != raw[key]],
        **{key: value for key, value in row.items() if key != "boot_id"},
    )


def server_status(env):
    return run_cli(env, "server", "status")[2]["data"]


def idle():
    limit = 8
    device = serial()
    env = fresh_env(AGENT_PHONE_IDLE_S=str(limit))
    try:
        run_cli(env, "server", "stop")
        ms, code, wire = run_cli(env, "snapshot")
        emit(
            check="idle_first_snapshot",
            ms=round(ms),
            ok=bool(wire and wire["ok"]),
            idle_limit_s=server_status(env)["idle_limit_s"],
        )

        started = time.monotonic()
        oks = 0
        last_use = started
        while time.monotonic() - started < 3 * limit:
            oks += bool(run_cli(env, "snapshot")[2]["ok"])
            last_use = time.monotonic()
            time.sleep(2)
        status = server_status(env)
        emit(
            check="busy_server_survives",
            seconds=round(time.monotonic() - started),
            snapshots_ok=oks,
            running=status["running"],
            idle_for_s=status["idle_for_s"],
        )

        gone = wait_until(lambda: not server_status(env)["running"], 4 * limit)
        emit(
            check="idle_server_stops",
            limit_s=limit,
            gone_after_last_command_s=gone and round(time.monotonic() - last_use, 1),
            server=bool(shell(device, SERVER).strip()),
            watchdog=bool(shell(device, WATCHDOG).strip()),
        )

        ms, code, wire = run_cli(env, "snapshot")
        emit(
            check="next_command_starts_it_again",
            ms=round(ms),
            ok=bool(wire and wire["ok"]),
            running=server_status(env)["running"],
        )
    finally:
        run_cli(env, "server", "stop")
        emit(check="server_left", running=bool(shell(device, SERVER).strip()))


def idle_default():
    """The shipped 15 minute limit, waited out. It takes about 16 minutes."""
    device = serial()
    env = fresh_env()
    try:
        run_cli(env, "server", "stop")
        ms, code, wire = run_cli(env, "snapshot")
        last_use = time.monotonic()
        emit(
            check="default_limit_first_snapshot",
            ms=round(ms),
            ok=bool(wire and wire["ok"]),
            idle_limit_s=server_status(env)["idle_limit_s"],
        )
        gone = wait_until(lambda: not server_status(env)["running"], 20 * 60, gap_s=20)
        emit(
            check="default_limit_server_stops",
            gone_after_last_command_s=gone and round(time.monotonic() - last_use),
            watchdog=bool(shell(device, WATCHDOG).strip()),
        )
    finally:
        run_cli(env, "server", "stop")
        emit(check="server_left", running=bool(shell(device, SERVER).strip()))


HOLDER = (
    "import time\n"
    "from agent_phone import open_phone\n"
    "with open_phone(command='probe holder') as phone:\n"
    "    print('held', flush=True)\n"
    "    time.sleep(4)\n"
)


def concurrent():
    device = serial()
    env = fresh_env()
    try:
        run_cli(env, "server", "stop")
        run_cli(env, "snapshot")
        holder = subprocess.Popen(
            [sys.executable, "-I", "-c", HOLDER], stdout=subprocess.PIPE, text=True, env=env
        )
        assert holder.stdout.readline().strip() == "held"
        held_at = time.monotonic()
        ms, code, wire = run_cli({**env, "AGENT_PHONE_LOCK_WAIT_S": "0"}, "snapshot")
        emit(
            check="second_process_with_no_wait",
            ms=round(ms),
            exit=code,
            error=wire["error"]["code"],
            delivery=wire["delivery"],
            message=wire["error"]["message"],
        )
        ms, code, wire = run_cli({**env, "AGENT_PHONE_LOCK_WAIT_S": "10"}, "snapshot")
        emit(
            check="second_process_that_waits",
            ms=round(ms),
            exit=code,
            ok=wire["ok"],
            waited_for_holder_s=round(time.monotonic() - held_at, 1),
        )
        holder.wait(timeout=30)

        results = []
        workers = [
            threading.Thread(
                target=lambda: results.append(run_cli(env, "snapshot")[:2] + (time.monotonic(),))
            )
            for _ in range(4)
        ]
        start = time.monotonic()
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()
        emit(
            check="four_at_once",
            exits=sorted(code for _, code, _ in results),
            seconds=round(time.monotonic() - start, 2),
            single_ms=round(statistics.median(ms for ms, _, _ in results)),
        )
    finally:
        run_cli(env, "server", "stop")
        emit(check="server_left", running=bool(shell(device, SERVER).strip()))


def old_dump(device):
    """The old `uiautomator dump`, which is its own UiAutomation client. It prints its success
    line, or the shell prints `Killed` when the client's registration throws."""
    done = adb("-s", device, "shell", "uiautomator dump /dev/stdout")
    text = (done.stdout + done.stderr).replace("\n", " ")
    return {
        "exit": done.returncode,
        "worked": done.returncode == 0 and "dumped to" in text,
        "tail": text[-60:],
    }


def stop():
    device = serial()
    env = fresh_env()
    try:
        run_cli(env, "server", "start")
        emit(check="old_dump_while_server_runs", **old_dump(device))
        ms, code, wire = run_cli(env, "server", "stop")
        emit(check="server_stop", ms=round(ms), exit=code, running=wire["data"]["running"])
        emit(
            check="after_stop",
            pgrep_server=shell(device, SERVER).split(),
            pgrep_watchdog=shell(device, WATCHDOG).split(),
            ps_lines_with_uia2=[
                line
                for line in shell(device, "ps -A -o PID,ARGS").splitlines()
                if "uia2" in line and "pgrep" not in line
            ][:3],
            lastuse_file=shell(device, f"ls {LASTUSE} 2>&1").strip(),
            forwards=[line for line in adb("forward", "--list").stdout.splitlines() if device in line],
        )
        emit(check="old_dump_after_stop", **old_dump(device))
        run_cli(env, "server", "stop")
        emit(check="stop_again", exit=run_cli(env, "server", "stop")[1])
    finally:
        run_cli(env, "server", "stop")


def uiautomator_pids(device):
    return set(shell(device, "pgrep -x uiautomator").split())


def foreign():
    """Another UiAutomation client (`uiautomator events`, started here and killed here) holds
    the device while agent-phone starts its server."""
    device = serial()
    env = fresh_env()
    before = uiautomator_pids(device)
    holder = set()
    try:
        run_cli(env, "server", "stop")
        shell(device, "nohup uiautomator events </dev/null >/dev/null 2>&1 &")
        wait_until(lambda: uiautomator_pids(device) - before, 10)
        holder = uiautomator_pids(device) - before
        emit(
            check="foreign_client_running",
            pids=len(holder),
            accessibility_enabled=shell(device, "settings get secure accessibility_enabled").strip(),
        )
        ms, code, wire = run_cli(env, "snapshot")
        emit(
            check="snapshot_while_foreign_client_holds",
            ms=round(ms),
            exit=code,
            error=wire["error"]["code"],
            message=wire["error"]["message"],
            delivery=wire["delivery"],
        )
        shell(device, "".join(f"kill {pid}; " for pid in holder))
        wait_until(lambda: not (uiautomator_pids(device) & holder), 10)
        emit(
            check="foreign_client_stopped",
            left=len(uiautomator_pids(device) & holder),
            accessibility_enabled=shell(device, "settings get secure accessibility_enabled").strip(),
        )
        ms, code, wire = run_cli(env, "snapshot")
        emit(check="snapshot_after_foreign_client", ms=round(ms), ok=bool(wire and wire["ok"]))
    finally:
        shell(device, "".join(f"kill {pid}; " for pid in holder))
        run_cli(env, "server", "stop")
        emit(check="server_left", running=bool(shell(device, SERVER).strip()))


if __name__ == "__main__":
    {
        "facts": facts,
        "watchdog": watchdog,
        "accessibility": accessibility,
        "quirks": quirks,
        "bench": bench,
        "devices": devices,
        "idle": idle,
        "concurrent": concurrent,
        "stop": stop,
        "foreign": foreign,
        "idle-default": idle_default,
        "phases-once": lambda: print(json.dumps(phases(os.environ))),
    }[sys.argv[1]]()
