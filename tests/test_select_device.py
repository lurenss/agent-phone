import pytest

from agent_phone.core.device import Connected, Serial, select_device
from agent_phone.core.outcome import ErrorCode, Refusal

J7 = Connected(Serial("0a1b2c3d4e5f6a7b"), "SM_J730F", ready=True)
EMULATOR = Connected(Serial("emulator-5554"), "sdk_gphone64", ready=True)
UNAUTHORIZED = Connected(Serial("R58M1234567"), "", ready=False)


def refusal(connected, requested=None, ref_device=None):
    with pytest.raises(Refusal) as raised:
        select_device(connected, requested, ref_device)
    return raised.value


def test_the_only_ready_device_is_the_default():
    assert select_device([J7], None, None) == J7.serial
    assert select_device([UNAUTHORIZED, J7], None, None) == J7.serial


def test_several_ready_devices_and_no_choice_is_a_refusal_that_lists_them():
    error = refusal([J7, EMULATOR])
    assert error.code is ErrorCode.DEVICE_AMBIGUOUS
    assert J7.serial in error.message and EMULATOR.serial in error.message
    assert error.details["devices"] == [J7.serial, EMULATOR.serial]


def test_dash_d_picks_among_several():
    assert select_device([J7, EMULATOR], EMULATOR.serial, None) == EMULATOR.serial


def test_an_unknown_serial_is_a_refusal_even_when_one_device_is_connected():
    error = refusal([J7], requested=Serial("nope"))
    assert error.code is ErrorCode.NO_DEVICE
    assert "nope" in error.message and J7.serial in error.message


def test_no_device_at_all():
    error = refusal([])
    assert error.code is ErrorCode.NO_DEVICE
    assert "adb lists no device" in error.message


def test_a_device_that_is_not_ready_is_never_chosen():
    by_default = refusal([UNAUTHORIZED])
    by_name = refusal([UNAUTHORIZED], requested=UNAUTHORIZED.serial)
    assert by_default.code is by_name.code is ErrorCode.NO_DEVICE
    assert UNAUTHORIZED.serial in by_default.message and "not ready" in by_default.message
    assert "unauthorized" in by_name.message


def test_a_ref_names_its_device_and_needs_no_dash_d():
    assert select_device([J7, EMULATOR], None, EMULATOR.serial) == EMULATOR.serial
    assert select_device([J7, EMULATOR], EMULATOR.serial, EMULATOR.serial) == EMULATOR.serial


def test_dash_d_that_contradicts_the_ref_is_the_wrong_device():
    error = refusal([J7, EMULATOR], requested=J7.serial, ref_device=EMULATOR.serial)
    assert error.code is ErrorCode.WRONG_DEVICE
    assert error.details == {"requested": J7.serial, "ref_device": EMULATOR.serial}


def test_a_ref_to_a_device_that_is_gone_is_no_device():
    assert refusal([J7], ref_device=EMULATOR.serial).code is ErrorCode.NO_DEVICE
