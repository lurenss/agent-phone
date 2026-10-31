import io
import json
from pathlib import Path

import pytest
from fakes import EMULATOR_SERIAL, J7_SERIAL, FakeHub
from support import FakeClock

from agent_phone.cli.process import run
from agent_phone.cli.settings import Settings
from agent_phone.core.device import Connected, Serial
from agent_phone.core.outcome import ErrorCode, Refusal
from agent_phone.core.refs.store import SnapshotStore

J7 = Connected(J7_SERIAL, "SM_J730F", ready=True)
UNAUTHORIZED = Connected(Serial("R58M1234567"), "", ready=False)


def invoke(argv, hub, root=None, lock_wait_s=0.0, clock=None):
    out = io.StringIO()
    settings = Settings(state_root=root or Path("/nonexistent-agent-phone-root"), lock_wait_s=lock_wait_s)
    code = run(argv, hub, settings, out, clock or FakeClock())
    lines = out.getvalue().splitlines()
    assert len(lines) == 1, "one command prints one envelope"
    return code, json.loads(lines[0])


def test_devices_lists_the_facts_of_every_ready_device_and_none_for_the_rest():
    code, wire = invoke(["devices"], FakeHub([J7, UNAUTHORIZED]))
    assert code == 0 and wire["ok"] is True and wire["command"] == "devices" and wire["device"] is None
    ready, waiting = wire["data"]["devices"]
    assert ready["serial"] == J7_SERIAL and ready["api"] == 28 and ready["display"] == [1080, 1920]
    assert waiting == {"serial": "R58M1234567", "model": "", "ready": False, "profile": None}


def test_devices_never_reads_a_device_adb_does_not_list_as_ready():
    hub = FakeHub([J7, UNAUTHORIZED])
    invoke(["devices"], hub)
    assert hub.inspected == [J7_SERIAL]


def test_one_device_that_cannot_be_read_does_not_hide_the_others():
    emulator = Connected(EMULATOR_SERIAL, "emu", ready=True)
    hub = FakeHub([J7, emulator], problems={EMULATOR_SERIAL: "adb timed out."})
    code, wire = invoke(["devices"], hub)
    first, second = wire["data"]["devices"]
    assert code == 0 and first["api"] == 28
    assert second["problem"] == "adb timed out." and "api" not in second


def test_no_device_at_all_is_an_empty_list_not_an_error():
    code, wire = invoke(["devices"], FakeHub([]))
    assert code == 0 and wire["data"] == {"devices": []}


@pytest.mark.parametrize("argv", [[], ["bogus"], ["devices", "--bogus"], ["-d"]])
def test_bad_arguments_print_the_envelope_and_exit_two(argv):
    code, wire = invoke(argv, FakeHub([J7]))
    assert code == 2 and wire["ok"] is False
    assert wire["error"]["code"] == "INVALID_ARGS"
    assert (wire["delivery"], wire["retry"]) == ("not_delivered", "safe")


def test_a_refusal_from_the_transport_is_its_envelope():
    class Broken(FakeHub):
        def connected(self):
            raise Refusal(ErrorCode.TRANSPORT, "adb is not installed.")

    code, wire = invoke(["devices"], Broken([]))
    assert code == 1 and wire["error"]["code"] == "TRANSPORT"


def test_an_exception_nobody_expected_is_internal_and_still_one_envelope():
    class Broken(FakeHub):
        def connected(self):
            raise ValueError("boom")

    code, wire = invoke(["devices"], Broken([]))
    assert code == 1 and wire["error"]["code"] == "INTERNAL" and "boom" in wire["error"]["message"]


def test_server_start_then_stop_runs_the_servers_actions_and_prints_its_status(tmp_path):
    hub = FakeHub([J7])
    code, started = invoke(["server", "start"], hub, tmp_path)
    assert code == 0 and started["device"] == J7_SERIAL and started["data"]["running"] is True
    code, stopped = invoke(["server", "stop"], hub, tmp_path)
    assert code == 0 and stopped["data"]["running"] is False and stopped["data"]["idle_for_s"] is None
    assert hub.server(J7_SERIAL).calls == ["start", "stop"]


def test_server_commands_need_a_device_choice_like_every_other_command(tmp_path):
    emulator = Connected(EMULATOR_SERIAL, "emu", ready=True)
    hub = FakeHub([J7, emulator])
    code, wire = invoke(["server", "status"], hub, tmp_path)
    assert code == 1 and wire["error"]["code"] == "DEVICE_AMBIGUOUS"
    code, wire = invoke(["-d", EMULATOR_SERIAL, "server", "start"], hub, tmp_path)
    assert code == 0 and wire["device"] == EMULATOR_SERIAL
    assert hub.server(EMULATOR_SERIAL).running and not hub.server(J7_SERIAL).running
    code, wire = invoke(["-d", "nope", "server", "status"], hub, tmp_path)
    assert wire["error"]["code"] == "NO_DEVICE"


def test_starting_or_stopping_waits_for_the_device_lock_and_status_does_not(tmp_path):
    hub = FakeHub([J7])
    with SnapshotStore(tmp_path).lock(J7_SERIAL, FakeClock(), 0, "snapshot"):
        for action in ("start", "stop"):
            code, wire = invoke(["server", action], hub, tmp_path)
            assert code == 1 and wire["error"]["code"] == "DEVICE_BUSY"
            assert (wire["delivery"], wire["retry"]) == ("not_delivered", "safe")
        code, wire = invoke(["server", "status"], hub, tmp_path)
        assert code == 0
    assert hub.server(J7_SERIAL).calls == []
    assert invoke(["server", "start"], hub, tmp_path)[0] == 0


def test_the_lock_is_free_after_a_command_even_when_it_fails(tmp_path):
    class Failing(FakeHub):
        def server(self, serial):
            raise Refusal(ErrorCode.SERVER_UNAVAILABLE, "no")

    assert invoke(["server", "start"], Failing([J7]), tmp_path)[0] == 1
    with SnapshotStore(tmp_path).lock(J7_SERIAL, FakeClock(), 0):
        pass


@pytest.mark.parametrize(
    "argv",
    [
        ["-d", EMULATOR_SERIAL, "server", "start"],
        ["server", "start", "-d", EMULATOR_SERIAL],
        ["--device", EMULATOR_SERIAL, "server", "start"],
    ],
)
def test_dash_d_works_before_the_command_and_after_it(tmp_path, argv):
    hub = FakeHub([J7, Connected(EMULATOR_SERIAL, "emu", ready=True)])
    code, wire = invoke(argv, hub, tmp_path)
    assert code == 0 and wire["device"] == EMULATOR_SERIAL


def test_a_busy_server_command_still_names_its_device(tmp_path):
    with SnapshotStore(tmp_path).lock(J7_SERIAL, FakeClock(), 0):
        code, wire = invoke(["server", "stop"], FakeHub([J7]), tmp_path)
    assert wire["error"]["code"] == "DEVICE_BUSY" and wire["device"] == J7_SERIAL


def test_a_state_root_that_a_command_creates_is_closed_to_other_users(tmp_path):
    root = tmp_path / "agent-phone-home"
    invoke(["server", "start"], FakeHub([J7]), root)
    assert (root.stat().st_mode & 0o777) == 0o700
