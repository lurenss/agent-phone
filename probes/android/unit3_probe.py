"""Live checks for unit 3a (reading the screen). Run from the repo root:

    uv run python -I probes/android/unit3_probe.py windows
    uv run python -I probes/android/unit3_probe.py freshness
    uv run python -I probes/android/unit3_probe.py bench

Each subcommand prints one JSON line per result and ends with the list of inputs it sent.
Every input goes through `send`, which refuses anything outside ALLOWED, so a probe cannot
tap, type, press another key or open another app. SocksTun is never named here.
"""

import json
import os
import statistics
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

ADB = "adb"
ALLOWED_ACTIONS = frozenset(
    {
        "android.settings.SETTINGS",
        "android.settings.WIFI_SETTINGS",
        "android.bluetooth.adapter.action.REQUEST_ENABLE",
    }
)
ALLOWED_APPS = frozenset({"com.instagram.android", "com.facebook.pages.app"})
ALLOWED_KEYS = frozenset({"KEYCODE_BACK", "KEYCODE_HOME"})
DIALOG_ACTIVITY = "RequestPermissionHelperActivity"
INPUTS: list[str] = []
RAW = Path(__file__).resolve().parent / "raw"
CLI = str(Path(sys.executable).parent / "agent-phone")
INSTAGRAM = "com.instagram.android"
SETTLE_S = 2.0


def adb(*args, timeout=30):
    return subprocess.run([ADB, *args], capture_output=True, text=True, timeout=timeout)


def serial():
    rows = [line.split() for line in adb("devices").stdout.splitlines()[1:] if line.strip()]
    ready = [row[0] for row in rows if row[1] == "device"]
    assert len(ready) == 1, f"expected one ready device, found {ready}"
    return ready[0]


def shell(device, script):
    return adb("-s", device, "shell", script).stdout


def emit(**row):
    print(json.dumps(row), flush=True)


def send(device, kind, value):
    """The only door to the phone's input. `kind` is action, app or key."""
    allowed = {"action": ALLOWED_ACTIONS, "app": ALLOWED_APPS, "key": ALLOWED_KEYS}[kind]
    assert value in allowed, f"{kind} {value} is not on the allowed list"
    command = {
        "action": f"am start -a {value}",
        "app": f"monkey -p {value} -c android.intent.category.LAUNCHER 1",
        "key": f"input keyevent {value}",
    }[kind]
    INPUTS.append(f"{kind} {value}")
    return shell(device, command)


def focus(device):
    """The window Android says has input focus, from `dumpsys window` (a read, not an input)."""
    for line in shell(device, "dumpsys window | grep mCurrentFocus").splitlines():
        if "mCurrentFocus=" in line and "u0 " in line:
            return line.split("u0 ", 1)[1].rstrip("}").strip()
    return None


def open_phone_for_reads(device):
    from agent_phone.adapters.uiautomator2.adb import SubprocessAdb
    from agent_phone.adapters.uiautomator2.phone import U2Hub
    from agent_phone.cli.settings import Settings

    settings = Settings.from_environment()
    return U2Hub(SubprocessAdb(settings.adb), settings.idle_limit_s).open(device)


def windows_of(phone):
    screen = phone.read()
    return [
        {
            "package": w.package,
            "kind": w.kind.value,
            "bounds": [w.bounds.left, w.bounds.top, w.bounds.right, w.bounds.bottom],
            "nodes": len(screen.subtree(w.root)),
        }
        for w in screen.windows
    ], screen.rotation.value


def wait_until(check, deadline_s, gap_s=0.25):
    start = time.monotonic()
    while time.monotonic() - start < deadline_s:
        value = check()
        if value:
            return value
        time.sleep(gap_s)
    return None


def sample_windows(device, phone, label, reads=20):
    """`reads` dumps in a row. The order of windows is the thing under test, so every distinct
    order is counted, and the focus Android reports is read before and after."""
    focus_before = focus(device)
    orders = Counter()
    last = None
    for _ in range(reads):
        last, rotation = windows_of(phone)
        orders[tuple((w["package"], tuple(w["bounds"])) for w in last)] += 1
    focus_after = focus(device)
    emit(
        check="window_order",
        screen=label,
        reads=reads,
        rotation=rotation,
        distinct_orders=len(orders),
        windows=last,
        focus_before=focus_before,
        focus_after=focus_after,
        first_window_is_focused=bool(
            focus_before and last and focus_before.startswith(last[0]["package"] + "/")
        ),
    )


def windows():
    """Is the first window of the dump the window with input focus, and does the dump say so.
    The dialog is the system's Bluetooth enable request: it only asks, and BACK declines it."""
    device = serial()
    assert shell(device, "settings get global bluetooth_on").strip() == "0", "Bluetooth is on, no dialog"
    phone = open_phone_for_reads(device)
    try:
        send(device, "app", "com.instagram.android")
        wait_until(lambda: (focus(device) or "").startswith("com.instagram.android/"), 15)
        time.sleep(3)
        sample_windows(device, phone, "instagram feed", 20)

        send(device, "action", "android.bluetooth.adapter.action.REQUEST_ENABLE")
        shown = wait_until(lambda: DIALOG_ACTIVITY in (focus(device) or ""), 10)
        time.sleep(1)
        emit(check="dialog_shown", focused=bool(shown))
        RAW.mkdir(exist_ok=True)
        (RAW / "dialog-over-app.raw.xml").write_text(phone._dump())
        sample_windows(device, phone, "bluetooth dialog over instagram", 20)

        if DIALOG_ACTIVITY in (focus(device) or ""):
            send(device, "key", "KEYCODE_BACK")
        gone = wait_until(lambda: DIALOG_ACTIVITY not in (focus(device) or ""), 10)
        emit(check="dialog_dismissed", gone=bool(gone), focus=focus(device))
        sample_windows(device, phone, "instagram feed after the dialog", 5)
    finally:
        phone.close()
        emit(check="bluetooth_after", on=shell(device, "settings get global bluetooth_on").strip())


def plain_env():
    """The environment of a plain shell: no AGENT_PHONE_* variable, so the CLI runs its defaults
    (docs/solutions/a-probe-that-sets-every-variable-never-runs-the-default.md)."""
    return {k: v for k, v in os.environ.items() if not k.startswith("AGENT_PHONE_")}


def cli(*args):
    """One CLI process from spawn to exit: (ms, exit code, bytes printed, envelope or None)."""
    start = time.perf_counter()
    done = subprocess.run([CLI, *args], capture_output=True, text=True, env=plain_env(), timeout=60)
    ms = (time.perf_counter() - start) * 1000
    try:
        wire = json.loads(done.stdout)
    except ValueError:
        wire = None
    return ms, done.returncode, len(done.stdout.encode()), wire


def summary(values):
    return {
        "runs": len(values),
        "median_ms": round(statistics.median(values)),
        "min_ms": round(min(values)),
        "max_ms": round(max(values)),
    }


def foreground(device, package):
    return wait_until(lambda: (focus(device) or "").startswith(package + "/"), 15)


def from_instagram(device, action):
    """Start `action` from another app, so the transition crosses apps, as an agent's does."""
    send(device, "app", INSTAGRAM)
    foreground(device, INSTAGRAM)
    time.sleep(SETTLE_S)
    send(device, "action", action)


def first_reads(device, title, raw_name):
    """Open the phone cold, as a CLI call does when the server is down, and read until the active
    surface shows `title`. Records what the very first read held."""
    from agent_phone.core.outcome import Refusal
    from agent_phone.core.snapshot.surface import select_surface

    start = time.perf_counter()
    phone = open_phone_for_reads(device)
    try:
        reads = []
        while time.perf_counter() - start < 8:
            screen = phone.read()
            try:
                surface = select_surface(screen)
                shown = surface.window.package
                on_surface = any(n.attrs.text == title for n in screen.subtree(surface.root))
            except Refusal:
                shown, on_surface = None, False
            reads.append(
                {
                    "windows": [(w.package, w.active, len(screen.subtree(w.root))) for w in screen.windows],
                    "surface": shown,
                    "title_on_surface": on_surface,
                    "title_anywhere": any(n.attrs.text == title for n in screen.nodes),
                }
            )
            if len(reads) == 1 and reads[0]["surface"] != "com.android.settings":
                RAW.mkdir(exist_ok=True)
                (RAW / f"{raw_name}.raw.xml").write_text(phone._dump())
            if on_surface and len(reads) > 1:
                break
        return reads
    finally:
        phone.close()


def freshness(rounds=10):
    """After `am start`, does the next snapshot show the new screen? Three views of one question:
    what the first read after a cold open holds, `snapshot --settle` with the server already up,
    and `snapshot --settle` with the server down, which is the CLI's first call of a session."""
    device = serial()
    emit(check="host_load", loadavg=os.getloadavg(), cores=os.cpu_count())
    try:
        wrong, never = 0, 0
        for i in range(rounds):
            cli("server", "stop")
            from_instagram(device, "android.settings.WIFI_SETTINGS")
            reads = first_reads(device, "Wi-Fi", "app-starting")
            first = reads[0]
            wrong += first["surface"] == "com.android.systemui"
            never += not any(r["title_on_surface"] for r in reads)
            emit(check="first_read_after_am_start", round=i, reads=len(reads), **first)
        emit(
            check="first_read_summary",
            rounds=rounds,
            first_read_surface_was_the_status_bar=wrong,
            title_never_on_surface=never,
        )
        for variant in ("warm", "cold"):
            shown, wrong_surface, unsettled, times = 0, 0, 0, []
            for i in range(rounds):
                if variant == "cold":
                    cli("server", "stop")
                action, title = (
                    ("android.settings.WIFI_SETTINGS", "Wi-Fi")
                    if i % 2 == 0
                    else ("android.settings.SETTINGS", "Settings")
                )
                from_instagram(device, action)
                ms, code, size, wire = cli("snapshot", "--settle")
                data = wire["data"] if wire and wire["ok"] else {}
                has_title = any(f'text "{title}" [' in line for line in data.get("tree", []))
                shown += has_title
                wrong_surface += data.get("app") == "com.android.systemui"
                unsettled += data.get("settled") != "settled"
                times.append(ms)
                emit(
                    check="settle_after_am_start",
                    variant=variant,
                    round=i,
                    target=title,
                    ok=bool(wire and wire["ok"]),
                    error=None if not wire or wire["ok"] else wire["error"]["code"],
                    app=data.get("app"),
                    settled=data.get("settled"),
                    title_shown=has_title,
                    ms=round(ms),
                )
            emit(
                check="settle_summary",
                variant=variant,
                rounds=rounds,
                title_shown=shown,
                surface_was_the_status_bar=wrong_surface,
                not_settled=unsettled,
                **summary(times),
            )
    finally:
        cli("server", "stop")
        send(device, "key", "KEYCODE_HOME")


COMMANDS = {"windows": windows, "freshness": freshness}

if __name__ == "__main__":
    try:
        COMMANDS[sys.argv[1]]()
    finally:
        emit(check="inputs_sent", inputs=INPUTS)
