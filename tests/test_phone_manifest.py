import json
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

import pytest
from host_support import EMULATOR_ROW, J7_FACTS, J7_ROW, MANIFEST_SCRIPT, FakeAdbServer, load_script

J7, EMULATOR, THIRD_PHONE = "0a1b2c3d4e5f6a7b", "emulator-5554", "R58M1234567"
UNAUTHORIZED_ROW = f"{J7}       unauthorized usb:1-1.4 transport_id:1"
NO_PERMISSIONS_ROW = (
    f"{THIRD_PHONE}            no permissions (missing udev rules? user is in the plugdev group);"
    " see [http://developer.android.com/tools/device.html] usb:1-1.3 transport_id:3"
)
THE_ONE_SHELL_LINE = "shell:getprop sys.boot_completed; getprop ro.build.version.release; dumpsys battery"
FIRST, SECOND, THIRD = "2026-11-17T13:00:05Z", "2026-11-17T13:00:35Z", "2026-11-17T13:01:05Z"
AS_MEASURED = {"booted": True, "android": "9", "battery": 100, "temp_c": 26.2}
UNHEALTHY_AND_NOT_READ = {"healthy": False, "battery": None, "tempC": None}


@pytest.fixture(scope="module")
def service():
    return load_script(MANIFEST_SCRIPT)


def j7_row(**changed):
    healthy = {
        "serial": J7,
        "model": "SM_J730F",
        "android": "9",
        "state": "device",
        "healthy": True,
        "problem": None,
        "battery": 100,
        "tempC": 26.2,
        "seenAt": FIRST,
    }
    return healthy | changed


def adb_with_the_j7():
    adb = FakeAdbServer(J7_ROW)
    adb.shells[J7] = J7_FACTS
    return adb


def rows(service, manifest):
    status, body = service.respond("/phones", manifest)
    assert status == 200
    return body["phones"]


@pytest.mark.parametrize(
    ("state", "facts", "problem"),
    [
        (None, None, "gone"),
        (None, AS_MEASURED, "gone"),
        ("unauthorized", None, "unauthorized"),
        ("unauthorized", AS_MEASURED, "unauthorized"),
        ("offline", None, "not_ready"),
        ("no permissions", None, "not_ready"),
        ("recovery", AS_MEASURED, "not_ready"),
        ("device", None, "no_answer"),
        ("device", AS_MEASURED | {"booted": False, "temp_c": 50.0, "battery": 5}, "booting"),
        ("device", AS_MEASURED | {"temp_c": 45.1, "battery": 5}, "hot"),
        ("device", AS_MEASURED | {"temp_c": 45.0}, None),
        ("device", AS_MEASURED | {"battery": 14}, "battery_low"),
        ("device", AS_MEASURED | {"battery": 15}, None),
        ("device", AS_MEASURED | {"battery": None, "temp_c": None}, None),
        ("device", AS_MEASURED, None),
    ],
)
def test_the_first_row_of_the_health_table_that_matches_is_the_problem(service, state, facts, problem):
    assert service.diagnose(state, facts and service.Facts(**facts)) == problem


def test_the_j7_as_measured_is_one_healthy_row_with_its_android_battery_and_temperature(service):
    manifest = service.check((), adb_with_the_j7().port, FIRST)
    assert service.respond("/phones", manifest) == (200, {"checkedAt": FIRST, "phones": [j7_row()]})
    assert service.respond("/health", manifest) == (200, {"status": "ok"})


def test_a_phone_that_adb_lists_no_more_stays_as_gone_and_comes_back_healthy(service):
    adb = adb_with_the_j7()
    first = service.check((), adb.port, FIRST)
    adb.rows.clear()
    second = service.check(first.phones, adb.port, SECOND)
    gone = j7_row(**UNHEALTHY_AND_NOT_READ, state=None, problem="gone")
    assert service.respond("/phones", second) == (200, {"checkedAt": SECOND, "phones": [gone]}), (
        "it keeps its model, and seenAt says when it left"
    )
    assert service.respond("/health", second) == (503, {"status": "degraded"})
    adb.rows.append(J7_ROW)
    third = service.check(second.phones, adb.port, THIRD)
    assert rows(service, third) == [j7_row(seenAt=THIRD)]


def test_an_unauthorized_phone_keeps_the_model_and_the_android_it_had(service):
    adb = adb_with_the_j7()
    first = service.check((), adb.port, FIRST)
    adb.rows[:] = [UNAUTHORIZED_ROW]
    second = service.check(first.phones, adb.port, SECOND)
    assert rows(service, second) == [
        j7_row(**UNHEALTHY_AND_NOT_READ, state="unauthorized", problem="unauthorized", seenAt=SECOND)
    ]
    never_authorized = rows(service, service.check((), adb.port, SECOND))[0]
    assert (never_authorized["model"], never_authorized["android"]) == ("", ""), "adb names neither"


def test_a_phone_in_any_other_adb_state_is_not_ready_and_is_not_asked(service):
    adb = FakeAdbServer(f"{J7}       offline usb:1-1.4 transport_id:1", NO_PERMISSIONS_ROW)
    listed = rows(service, service.check((), adb.port, FIRST))
    assert [(row["serial"], row["state"], row["problem"]) for row in listed] == [
        (J7, "offline", "not_ready"),
        (THIRD_PHONE, "no permissions", "not_ready"),
    ]
    assert adb.requests == ["host:devices-l"]


def test_a_phone_whose_shell_hangs_costs_one_deadline_and_its_neighbour_is_still_healthy(
    service, monkeypatch
):
    monkeypatch.setattr(service, "DEADLINE_S", 0.5)
    adb = FakeAdbServer(EMULATOR_ROW, J7_ROW)
    adb.shells = {EMULATOR: None, J7: J7_FACTS}
    started = time.monotonic()
    manifest = service.check((), adb.port, FIRST)
    assert 0.5 <= time.monotonic() - started < 1.5
    healthy, silent = rows(service, manifest)
    assert healthy == j7_row(), "the phone that adb lists after the silent one"
    assert silent == j7_row(
        **UNHEALTHY_AND_NOT_READ, serial=EMULATOR, model="sdk_gphone64_arm64", android="", problem="no_answer"
    )


def test_while_adb_does_not_answer_no_row_is_served_and_none_is_forgotten(service):
    adb = adb_with_the_j7()
    first = service.check((), adb.port, FIRST)
    with socket.socket() as unused:
        unused.bind(("127.0.0.1", 0))
        dead = unused.getsockname()[1]
    down = service.check(first.phones, dead, SECOND)
    status, body = service.respond("/phones", down)
    assert status == 503 and body.keys() == {"error"} and body["error"]["type"] == "adb_down"
    assert service.respond("/health", down) == (503, {"status": "degraded"})
    adb.rows.clear()
    back = service.check(down.phones, adb.port, THIRD)
    assert rows(service, back) == [j7_row(**UNHEALTHY_AND_NOT_READ, state=None, problem="gone")]


def test_adb_only_ever_gets_the_listing_and_the_one_shell_line_that_reads(service):
    adb = FakeAdbServer(J7_ROW, EMULATOR_ROW, NO_PERMISSIONS_ROW)
    adb.shells = {J7: J7_FACTS, EMULATOR: J7_FACTS}
    manifest = service.check((), adb.port, FIRST)
    adb.rows[:] = [UNAUTHORIZED_ROW, EMULATOR_ROW]
    manifest = service.check(manifest.phones, adb.port, SECOND)
    adb.rows.clear()
    service.check(manifest.phones, adb.port, THIRD)
    assert set(adb.requests) == {
        "host:devices-l",
        f"host:transport:{J7}",
        f"host:transport:{EMULATOR}",
        THE_ONE_SHELL_LINE,
    }


def run_service(*flags, adb_port=1):
    return subprocess.Popen(
        [sys.executable, "-IS", str(MANIFEST_SCRIPT), "--port", "0", *flags],
        env={"ANDROID_ADB_SERVER_PORT": str(adb_port)},
        stderr=subprocess.PIPE,
        text=True,
    )


def get(port, path):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=10) as answer:
            return answer.status, json.load(answer)
    except urllib.error.HTTPError as refused:
        return refused.code, json.load(refused)


def test_the_file_itself_serves_the_manifest_and_writes_each_change_to_stderr():
    adb = adb_with_the_j7()
    process = run_service("--every", "0.1", adb_port=adb.port)
    watchdog = threading.Timer(30, process.kill)
    watchdog.start()

    def line():
        return json.loads(process.stderr.readline())

    try:
        start = line()
        port = start["port"]
        assert start == {"event": "manifest.start", "host": "127.0.0.1", "port": port} and port > 0
        assert line() == {"event": "phone.changed", "serial": J7, "problem": None}
        status, body = get(port, "/phones")
        assert status == 200 and re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", body["checkedAt"])
        assert body["phones"] == [j7_row(seenAt=body["checkedAt"])]
        assert get(port, "/health") == (200, {"status": "ok"})
        status, body = get(port, "/nope")
        assert status == 404 and body["error"]["type"] == "not_found"

        adb.rows.clear()
        assert line() == {"event": "phone.changed", "serial": J7, "problem": "gone"}
        assert get(port, "/health") == (503, {"status": "degraded"})
        assert get(port, "/phones")[1]["phones"][0]["problem"] == "gone"
    finally:
        watchdog.cancel()
        process.kill()
        process.wait()
        process.stderr.close()
    assert set(adb.requests) == {"host:devices-l", f"host:transport:{J7}", THE_ONE_SHELL_LINE}


@pytest.mark.parametrize("flags", [["--port", "65536"], ["--every", "0"], ["--every", "soon"]])
def test_a_flag_with_a_bad_value_ends_the_service_at_once_with_a_usage_message(flags):
    process = run_service(*flags)
    try:
        assert process.wait(timeout=20) == 2 and "usage: phone-manifest" in process.stderr.read()
    finally:
        process.kill()
        process.stderr.close()
