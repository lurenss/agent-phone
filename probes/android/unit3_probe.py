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


SCREENS = (
    ("stock Settings", "action", "android.settings.SETTINGS", "com.android.settings", False),
    (
        "system dialog",
        "action",
        "android.bluetooth.adapter.action.REQUEST_ENABLE",
        "com.android.settings",
        True,
    ),
    ("Instagram feed", "app", INSTAGRAM, INSTAGRAM, False),
    ("Business Suite home", "app", "com.facebook.pages.app", "com.facebook.pages.app", False),
)
"""Label, the kind of input that shows it, the input, the package it should show, and whether it
is a dialog. The dialog opens over whatever is in front, which is Settings when this order runs."""


def show(device, kind, value):
    send(device, kind, value)
    if value.endswith("REQUEST_ENABLE"):
        return wait_until(lambda: DIALOG_ACTIVITY in (focus(device) or ""), 10)
    return foreground(device, value if kind == "app" else "com.android.settings")


def settled_screen(package, dialog):
    """`snapshot --settle` until it says settled for the package that should be showing."""
    for attempt in range(1, 11):
        ms, code, size, wire = cli("snapshot", "--settle")
        data = wire["data"] if wire and wire["ok"] else {}
        if data.get("settled") == "settled" and data.get("app") == package and data.get("dialog") == dialog:
            return attempt, round(ms)
        time.sleep(1)
    return None, None


def bench_screen(label, package, dialog):
    errors, wrong, sizes, lines, times, apps = 0, 0, [], [], [], set()
    for _ in range(20):
        ms, code, size, wire = cli("snapshot")
        ok = bool(wire and wire["ok"] and code == 0)
        errors += not ok
        times.append(ms)
        sizes.append(size)
        data = wire["data"] if ok else {}
        apps.add(data.get("app"))
        wrong += not (data.get("app") == package and data.get("dialog") == dialog)
        lines.append(len(data.get("tree", [])))
    settle_times, settled = [], 0
    for _ in range(10):
        ms, code, size, wire = cli("snapshot", "--settle")
        settle_times.append(ms)
        settled += bool(wire and wire["ok"] and wire["data"]["settled"] == "settled")
    emit(
        check="warm_snapshot",
        screen=label,
        errors=errors,
        wrong_screen=wrong,
        apps=sorted(a or "" for a in apps),
        bytes=[min(sizes), max(sizes)],
        under_8_kb=max(sizes) < 8 * 1024,
        tree_lines=[min(lines), max(lines)],
        **summary(times),
    )
    emit(check="warm_settle", screen=label, settled=settled, **summary(settle_times))


def bench():
    """Done-when 1 of docs/plan.md: `snapshot` as a CLI process, 20 runs on each of four settled
    screens, from a plain shell. Each run must succeed, show the screen that was asked for, and
    print under 8 KB."""
    device = serial()
    emit(
        check="host_load",
        loadavg=os.getloadavg(),
        cores=os.cpu_count(),
        phone_uptime=shell(device, "uptime").strip(),
    )
    try:
        cli("server", "stop")
        for label, kind, value, package, dialog in SCREENS:
            if not show(device, kind, value):
                emit(check="screen_not_shown", screen=label)
                continue
            attempts, settle_ms = settled_screen(package, dialog)
            emit(check="settled", screen=label, attempts=attempts, ms=settle_ms)
            if attempts is None:
                continue
            bench_screen(label, package, dialog)
            if dialog:
                if DIALOG_ACTIVITY in (focus(device) or ""):
                    send(device, "key", "KEYCODE_BACK")
                wait_until(lambda: DIALOG_ACTIVITY not in (focus(device) or ""), 10)
            if label == "Instagram feed":
                emit(check="phases_fresh_process", screen=label, **phases_of_a_cli_run())
    finally:
        cli("server", "stop")
        send(device, "key", "KEYCODE_HOME")


def phases_of_a_cli_run():
    """Where one warm CLI run spends its time, from unit 2's timers, on the screen showing now."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("unit2_probe", Path(__file__).with_name("unit2_probe.py"))
    unit2 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(unit2)
    return unit2.phases_fresh(unit2.fresh_env(), repeats=7)


def check(name, ok, **facts):
    emit(check=name, ok=bool(ok), **facts)
    return bool(ok)


def data_of(*args):
    ms, code, size, wire = cli(*args)
    return wire, (wire or {}).get("data", {}), size


def settings_commands(device):
    """find, get, is and --root on stock Settings, whose content is the system's own."""
    show(device, "action", "android.settings.SETTINGS")
    settled_screen("com.android.settings", False)
    wire, found, _ = data_of("find", "--name", "connections", "--exact")
    check(
        "find_one_tile",
        found.get("count") == 1 and len(found.get("matches", [])) == 1,
        count=found.get("count"),
    )
    ref = found["matches"][0].split()[0]
    printed = found["matches"][0].rsplit(" [", 1)[1].rstrip("]")
    wire, bounds, _ = data_of("get", ref, "--property", "bounds")
    check("get_bounds_equal_the_printed_bounds", ",".join(map(str, bounds.get("value", []))) == printed)
    wire, text, _ = data_of("get", ref)
    check("get_text_starts_with_the_name", str(text.get("value", "")).startswith("Connections"))
    wire, visible, _ = data_of("is", ref)
    wire, enabled, _ = data_of("is", ref, "--property", "enabled")
    wire, checked, _ = data_of("is", ref, "--property", "checked")
    check(
        "is_visible_enabled_not_checked",
        (visible.get("value"), enabled.get("value"), checked.get("value")) == (True, True, False),
    )
    wire, whole, whole_size = data_of("snapshot")
    wire, skeleton, skeleton_size = data_of("snapshot", "--skeleton")
    lists = [line for line in skeleton.get("tree", []) if "(+" in line]
    check(
        "skeleton_folds_the_tile_list",
        lists and skeleton_size < whole_size,
        whole_bytes=whole_size,
        skeleton_bytes=skeleton_size,
        folded_collections=len(lists),
    )
    list_ref = lists[0].split()[0].replace(skeleton["id"], whole["id"])
    wire, drilled, drilled_size = data_of("snapshot", "--root", list_ref)
    numbers = [
        line.split()[0].split(":")[1] for line in drilled.get("tree", []) if line.lstrip().startswith("@")
    ]
    check(
        "root_drills_with_the_same_numbers",
        drilled.get("id") not in (None, whole["id"])
        and numbers[0] == list_ref.split(":")[1]
        and len(drilled["tree"]) > 1,
        lines=len(drilled.get("tree", [])),
    )
    wire, rows, _ = data_of("find", "--role", "button", "--root", list_ref, "--count")
    wire, everywhere, _ = data_of("find", "--role", "button", "--count")
    check(
        "find_root_narrows",
        0 < rows.get("count", 0) <= everywhere.get("count", 0),
        in_root=rows.get("count"),
        all=everywhere.get("count"),
    )
    wire, nothing, _ = data_of("find", "--name", "no such element on this screen", "--count")
    check("find_nothing_is_zero_not_an_error", wire["ok"] and nothing.get("count") == 0)
    wire, stale, _ = data_of("get", "@zzzzz:e1")
    check("get_unknown_snapshot_is_refused", not wire["ok"] and wire["error"]["code"] == "SNAPSHOT_NOT_FOUND")


def instagram_commands(device):
    """The skeleton fix and the surface flags on the Instagram feed. Only counts and shapes are
    recorded, because the feed shows private content."""
    show(device, "app", INSTAGRAM)
    settled_screen(INSTAGRAM, False)
    wire, whole, whole_size = data_of("snapshot")
    wire, skeleton, skeleton_size = data_of("snapshot", "--skeleton")
    tree = skeleton.get("tree", [])
    folded = [line for line in tree if "(+" in line]
    check(
        "skeleton_shows_the_pages_and_folds_the_feed_list",
        len(tree) < len(whole["tree"]) and folded and not tree[0].endswith(")") and "(+" not in tree[0],
        whole_lines=len(whole["tree"]),
        skeleton_lines=len(tree),
        folded_lines=len(folded),
        first_line_role=tree[0].split()[1] if tree else None,
        whole_bytes=whole_size,
        skeleton_bytes=skeleton_size,
    )
    for flag, code in (("dialog", "NO_SURFACE"), ("keyboard", "NO_SURFACE")):
        wire, _, _ = data_of("snapshot", "--surface", flag)
        check(f"surface_{flag}_is_not_on_the_feed", not wire["ok"] and wire["error"]["code"] == code)
    wire, everything, size = data_of("snapshot", "--surface", "all")
    heads = [line for line in everything.get("tree", []) if line.startswith("group ")]
    check(
        "surface_all_names_every_window", len(heads) == 2 and size < 8 * 1024, windows=len(heads), bytes=size
    )
    others = {other["app"]: other["id"] for other in whole.get("others", [])}
    wire, strip, _ = data_of("snapshot", "--window", str(others.get("com.android.systemui", 99)))
    check(
        "window_id_from_others_describes_that_window",
        strip.get("app") == "com.android.systemui",
        status_bar_id=others.get("com.android.systemui"),
    )
    wire, count, _ = data_of("find", "--role", "button", "--count")
    check("find_counts_buttons", wire["ok"] and count.get("count", 0) > 0, count=count.get("count"))


def dialog_commands(device):
    """The surface flags on the system's Bluetooth enable dialog, which only asks."""
    show(device, "action", "android.bluetooth.adapter.action.REQUEST_ENABLE")
    try:
        settled_screen("com.android.settings", True)
        wire, dialog, _ = data_of("snapshot", "--surface", "dialog")
        names = [line.split('"')[1] for line in dialog.get("tree", []) if line.lstrip().startswith("@")]
        check(
            "surface_dialog_is_the_dialog",
            dialog.get("dialog") is True and names == ["Deny", "Allow"],
            buttons=names,
        )
        wire, found, _ = data_of("find", "--text", "bluetooth", "--surface", "dialog", "--count")
        check("find_in_the_dialog", found.get("count") == 1, count=found.get("count"))
        wire, deny, _ = data_of("find", "--name", "deny", "--exact", "--surface", "dialog")
        ref = deny["matches"][0].split()[0]
        wire, enabled, _ = data_of("is", ref, "--property", "enabled")
        check("is_enabled_on_a_dialog_button", enabled.get("value") is True)
        wire, everything, _ = data_of("snapshot", "--surface", "all")
        check("surface_all_over_a_dialog", sum(line.startswith("group ") for line in everything["tree"]) == 2)
    finally:
        if DIALOG_ACTIVITY in (focus(device) or ""):
            send(device, "key", "KEYCODE_BACK")
        wait_until(lambda: DIALOG_ACTIVITY not in (focus(device) or ""), 10)


def commands():
    """The new reading commands on live screens, from a plain shell."""
    device = serial()
    try:
        cli("server", "stop")
        settings_commands(device)
        instagram_commands(device)
        dialog_commands(device)
    finally:
        cli("server", "stop")
        send(device, "key", "KEYCODE_HOME")


def transition(rounds=10):
    """What reads show right after `am start` with the server already up: the old screen, an empty
    window, or the new one, and whether two reads in a row ever agree on something that is not the
    new screen. That is A2-5 observed instead of inferred."""
    from agent_phone.core.outcome import Refusal
    from agent_phone.core.snapshot.surface import select_surface
    from agent_phone.core.wait.predicate import Settled, holds

    device = serial()
    phone = open_phone_for_reads(device)
    fooled, first_old, shown = 0, 0, []
    try:
        for i in range(rounds):
            from_instagram(device, "android.settings.WIFI_SETTINGS")
            start = time.perf_counter()
            previous, states, agreed_on_old = None, [], False
            while time.perf_counter() - start < 6:
                screen = phone.read()
                ms = round((time.perf_counter() - start) * 1000)
                try:
                    surface = select_surface(screen)
                    nodes = len(screen.subtree(surface.root))
                    new = any(n.attrs.text == "Wi-Fi" for n in screen.subtree(surface.root))
                    state = "new" if new else ("empty" if nodes <= 1 else "old")
                except Refusal:
                    state = "none"
                if previous is not None and state != "new" and holds(Settled(), previous, screen):
                    agreed_on_old = True
                states.append((ms, state))
                previous = screen
                if state == "new" and len(states) > 1 and states[-2][1] == "new":
                    break
            first_new = next((ms for ms, state in states if state == "new"), None)
            fooled += agreed_on_old
            first_old += states[0][1] != "new"
            shown.append(first_new)
            emit(
                check="reads_after_am_start",
                round=i,
                reads=len(states),
                first_state=states[0][1],
                first_read_ms=states[0][0],
                first_new_ms=first_new,
                states=[state for _, state in states],
                two_reads_agreed_on_a_screen_that_was_not_new=agreed_on_old,
            )
        emit(
            check="transition_summary",
            rounds=rounds,
            first_read_was_not_the_new_screen=first_old,
            settle_would_have_stopped_early=fooled,
            new_screen_after_ms=summary([ms for ms in shown if ms is not None]) if any(shown) else None,
        )
    finally:
        phone.close()
        cli("server", "stop")
        send(device, "key", "KEYCODE_HOME")


COMMANDS = {
    "windows": windows,
    "freshness": freshness,
    "transition": transition,
    "bench": bench,
    "commands": commands,
}

if __name__ == "__main__":
    try:
        COMMANDS[sys.argv[1]]()
    finally:
        emit(check="inputs_sent", inputs=INPUTS)
