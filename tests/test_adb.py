import pytest
from support import ROOT

from agent_phone.adapters.uiautomator2.adb import SubprocessAdb, parse_devices
from agent_phone.core.device import Connected, Serial
from agent_phone.core.outcome import ErrorCode, Refusal

LISTING = (ROOT / "tests" / "fixtures" / "adb" / "devices.txt").read_text()


def test_every_row_after_the_header_is_a_device_and_only_state_device_is_ready():
    assert parse_devices(LISTING) == (
        Connected(Serial("0a1b2c3d4e5f6a7b"), "SM_J730F", ready=True),
        Connected(Serial("emulator-5554"), "sdk_gphone64_arm64", ready=True),
        Connected(Serial("R58M1234567"), "", ready=False),
        Connected(Serial("0123456789ABCDEF"), "", ready=False),
    )


def test_no_devices_is_an_empty_list():
    assert parse_devices("List of devices attached\n\n") == ()


def test_an_answer_without_the_header_is_a_transport_failure():
    with pytest.raises(Refusal) as raised:
        parse_devices("adb: command not found")
    assert raised.value.code is ErrorCode.TRANSPORT


def test_a_missing_adb_binary_is_a_refusal_that_says_so():
    with pytest.raises(Refusal) as raised:
        SubprocessAdb("no-such-adb-binary").run(("devices",))
    assert raised.value.code is ErrorCode.TRANSPORT
    assert "not installed" in raised.value.message


def test_an_adb_call_that_hangs_is_cut_off_at_its_deadline():
    with pytest.raises(Refusal) as raised:
        SubprocessAdb("sleep").run(("5",), timeout_s=0.2)
    assert raised.value.code is ErrorCode.TRANSPORT
    assert "0.2 s" in raised.value.message
