"""Live checks for unit 3a (reading the screen). Run from the repo root:

    uv run python -I probes/android/unit3_probe.py windows
    uv run python -I probes/android/unit3_probe.py freshness
    uv run python -I probes/android/unit3_probe.py bench

Each subcommand prints one JSON line per result and ends with the list of inputs it sent.
Every input goes through `send`, which refuses anything outside ALLOWED, so a probe cannot
tap, type, press another key or open another app. SocksTun is never named here.
"""

import json
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


COMMANDS = {"windows": windows}

if __name__ == "__main__":
    try:
        COMMANDS[sys.argv[1]]()
    finally:
        emit(check="inputs_sent", inputs=INPUTS)
