import io
import json

import pytest
from fakes import EMULATOR_SERIAL, J7_SERIAL, FakeHub

from agent_phone.cli.main import run
from agent_phone.core.device import Connected, Serial
from agent_phone.core.outcome import ErrorCode, Refusal

J7 = Connected(J7_SERIAL, "SM_J730F", ready=True)
UNAUTHORIZED = Connected(Serial("R58M1234567"), "", ready=False)


def invoke(argv, hub):
    out = io.StringIO()
    code = run(argv, hub, out)
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
