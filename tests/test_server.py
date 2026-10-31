import hashlib
from pathlib import Path

import pytest
from fakes import J7_SERIAL
from support import FakeClock

from agent_phone.adapters.uiautomator2 import server as lifetime
from agent_phone.adapters.uiautomator2.adb import AdbResult
from agent_phone.adapters.uiautomator2.server import Forward, Server, parse_status, touch_interval
from agent_phone.core.outcome import ErrorCode, Refusal

JAR_BYTES = b"jar-bytes"
JAR_SHA = hashlib.sha1(JAR_BYTES).hexdigest()


class FakePhone:
    """What `adb` shows of a phone's server, for the scripts the adapter sends. It matches a
    script by equality with the one the adapter builds, so a changed script still reaches it."""

    def __init__(self, idle_limit_s=900):
        self.server = False
        self.watchdog = False
        self.answers = False
        self.jar_sha = None
        self.ignores_sigterm = False
        self.polls_until_gone = 0
        self.calls = []
        self.leftover_forwards = []
        self.limit = idle_limit_s

    def run(self, args, timeout_s=15.0):
        match args:
            case ("-s", _, "shell", script):
                return AdbResult(0, self.shell(script), "")
            case ("-s", _, "push", _, _):
                self.calls.append("push")
                self.jar_sha = JAR_SHA
            case ("-s", _, "forward", "tcp:0", _):
                return AdbResult(0, "50123\n", "")
            case ("forward", "--list"):
                return AdbResult(
                    0, "".join(f"{J7_SERIAL} tcp:{p} tcp:9008\n" for p in self.leftover_forwards), ""
                )
            case ("-s", _, "forward", "--remove", port):
                self.calls.append(f"unforward {port}")
        return AdbResult(0, "", "")

    def shell(self, script):
        if script == lifetime.STATUS_SCRIPT:
            lines = [f"server={4242 if self.server else ''}", f"watchdog={4243 if self.watchdog else ''}"]
            if self.watchdog:
                lines.append(f"limit={self.limit}")
            return "\n".join([*lines, "now=1000", "last=997"])
        if script == lifetime.start_script(self.limit):
            self.calls.append("start")
            self.server = self.watchdog = True
            self.answers = True
        elif script == lifetime.STOP_SCRIPT:
            self.calls.append("stop")
            self.watchdog = False
            if not self.ignores_sigterm:
                self.server = False
        elif script == lifetime.KILL_SERVER_SCRIPT:
            self.calls.append("kill -9")
            self.server = False
        elif script.startswith("sha1sum"):
            return f"{self.jar_sha}  {lifetime.DEVICE_JAR}\n" if self.jar_sha else ""
        return ""

    def ping(self):
        return self.server and self.answers


class Rpc:
    def __init__(self, phone):
        self.phone = phone

    def ping(self, timeout_s=1.0):
        return self.phone.ping()


@pytest.fixture
def jar(tmp_path) -> Path:
    path = tmp_path / "u2.jar"
    path.write_bytes(JAR_BYTES)
    return path


def server_for(phone, jar, clock=None, limit=900):
    phone.limit = limit
    return Server(J7_SERIAL, phone, limit, clock or FakeClock(), jar, lambda port: Rpc(phone))


def test_a_phone_with_no_server_gets_the_jar_then_a_server_and_a_watchdog(jar):
    phone = FakePhone()
    status = server_for(phone, jar).start()
    assert phone.calls[:2] == ["push", "start"]
    assert (status.running, status.watchdog, status.idle_limit_s) == (True, True, 900)
    assert "unforward tcp:50123" in phone.calls, "the forward the command made is removed again"


def test_the_jar_is_pushed_only_when_it_is_missing_or_differs(jar):
    same = FakePhone()
    same.jar_sha = JAR_SHA
    server_for(same, jar).start()
    assert "push" not in same.calls and "start" in same.calls
    different = FakePhone()
    different.jar_sha = "0" * 40
    server_for(different, jar).start()
    assert different.calls[0] == "push"


def test_start_on_a_healthy_server_changes_nothing(jar):
    phone = FakePhone()
    server_for(phone, jar).start()
    phone.calls.clear()
    server_for(phone, jar).start()
    assert phone.calls == ["unforward tcp:50123"]


def test_start_repairs_a_running_server_that_lost_its_watchdog(jar):
    phone = FakePhone()
    server_for(phone, jar).start()
    phone.watchdog = False
    phone.calls.clear()
    status = server_for(phone, jar).start()
    assert "start" in phone.calls and status.watchdog


def test_a_server_that_runs_but_stays_silent_is_stopped_before_it_is_started_again(jar):
    phone = FakePhone()
    phone.server = True
    server_for(phone, jar).start()
    assert phone.calls[:3] == ["stop", "push", "start"]


def test_a_server_that_exits_as_it_starts_is_refused_within_seconds_and_names_the_likely_cause(jar):
    phone = FakePhone()
    original = phone.shell

    def start_then_die(script):
        out = original(script)
        if script == lifetime.start_script(900):
            phone.server = False
        return out

    phone.shell = start_then_die
    clock = FakeClock()
    with pytest.raises(Refusal) as raised:
        server_for(phone, jar, clock).start()
    assert raised.value.code is ErrorCode.SERVER_UNAVAILABLE
    assert "exited as it started" in raised.value.message and "UiAutomation client" in raised.value.message
    assert clock.time < 3, "it did not wait for the deadline"


def test_a_server_that_runs_but_never_answers_is_refused_at_the_deadline(jar):
    phone = FakePhone()
    original = phone.shell

    def start_but_stay_silent(script):
        out = original(script)
        if script == lifetime.start_script(900):
            phone.answers = False
        return out

    phone.shell = start_but_stay_silent
    clock = FakeClock()
    with pytest.raises(Refusal) as raised:
        server_for(phone, jar, clock).start()
    assert "20 s" in raised.value.message and "does not answer" in raised.value.message
    assert lifetime.START_DEADLINE_S <= clock.time <= lifetime.START_DEADLINE_S + lifetime.PING_GAP_S + 0.01


def test_stop_ends_the_server_and_its_watchdog_and_drops_forwards_left_behind(jar):
    phone = FakePhone()
    server_for(phone, jar).start()
    phone.leftover_forwards = [50001, 50002]
    phone.calls.clear()
    status = server_for(phone, jar).stop()
    assert (status.running, status.watchdog) == (False, False)
    assert phone.calls == ["stop", "unforward tcp:50001", "unforward tcp:50002"]


def test_stop_kills_a_server_that_ignores_the_polite_request(jar):
    phone = FakePhone()
    phone.server = True
    phone.ignores_sigterm = True
    status = server_for(phone, jar).stop()
    assert phone.calls[:2] == ["stop", "kill -9"] and not status.running


def test_stop_on_a_stopped_phone_is_fine(jar):
    assert server_for(FakePhone(), jar).stop().running is False


def test_a_forward_that_adb_does_not_number_is_a_transport_failure():
    class Odd:
        def run(self, args, timeout_s=15.0):
            return AdbResult(1, "", "error: device offline\n")

    with pytest.raises(Refusal) as raised:
        Forward.open(Odd(), J7_SERIAL)
    assert raised.value.code is ErrorCode.TRANSPORT and "device offline" in raised.value.message


@pytest.mark.parametrize(
    ("text", "running", "watchdog", "limit", "idle"),
    [
        ("server=4242\nwatchdog=4243\nlimit=900\nnow=1000\nlast=940\n", True, True, 900, 60),
        ("server=\nwatchdog=\nnow=1000\nlast=940\n", False, False, None, None),
        ("server=4242\nwatchdog=\nnow=1000\nlast=\n", True, False, None, None),
        ("server=4242\nwatchdog=4243\nlimit=6\nnow=1000\nlast=1005\n", True, True, 6, 0),
    ],
)
def test_the_status_text_the_phone_prints_becomes_a_status(text, running, watchdog, limit, idle):
    status = parse_status(text)
    assert (status.running, status.watchdog, status.idle_limit_s, status.idle_for_s) == (
        running,
        watchdog,
        limit,
        idle,
    )


@pytest.mark.parametrize(("limit", "every"), [(900, 60), (240, 60), (100, 25), (8, 2), (1, 1)])
def test_a_short_idle_limit_is_touched_often_enough_to_keep_a_busy_server_alive(limit, every):
    assert touch_interval(limit) == every
