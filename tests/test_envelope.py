import json

import pytest
from support import GOLDEN, fixture_screen, snapshot_of

from agent_phone.core.act.intent import ActionReport, TargetReport
from agent_phone.core.device import (
    BootId,
    Connected,
    DeviceIdentity,
    DeviceInfo,
    DeviceList,
    Listed,
    Package,
    Serial,
)
from agent_phone.core.envelope import HINTS, encode, exit_code, floor_envelope, to_wire
from agent_phone.core.geometry import Point, Rect, Size
from agent_phone.core.outcome import Acted, ErrorCode, Read, Refusal, Refused, SentState
from agent_phone.core.phone import NodeAddress, ServerStatus, Tap
from agent_phone.core.policy.engine import Clear, ClearReason
from agent_phone.core.role import Role
from agent_phone.core.snapshot.snapshot import SnapshotId

J7 = DeviceIdentity(Serial("0a1b2c3d4e5f6a7b"), BootId("8d3f6c1e-0b5a-4c2e-9f1d-2a7b3c4d5e6f"))
INFO = DeviceInfo(
    J7, "SM-J730F", 28, "armeabi-v7a", Size(1080, 1920), 420, "en-US", Package("ime.pkg"), frozenset()
)


def test_a_snapshot_read_prints_the_goldens_lines_under_its_id():
    snapshot = snapshot_of(fixture_screen("settings-home"), SnapshotId("q7m2k"), J7)
    wire = to_wire("snapshot", J7.serial, Read(snapshot))
    assert list(wire) == ["v", "ok", "command", "device", "data"]
    assert wire["device"] == J7.serial and wire["ok"] is True
    golden = (GOLDEN / "settings-home.compact.txt").read_text().splitlines()
    assert [line.replace("@q7m2k:", "@t0000:") for line in wire["data"]["tree"]] == golden


def test_the_encoding_has_no_spaces_between_tokens_and_keeps_non_ascii():
    snapshot = snapshot_of(fixture_screen("settings-home"), SnapshotId("q7m2k"), J7)
    text = encode(to_wire("snapshot", J7.serial, Read(snapshot)))
    assert text.startswith('{"v":1,"ok":true,"command":"snapshot","device":"0a1b2c3d4e5f6a7b","data":{')
    assert encode({"name": "Aeroplane mode…"}) == '{"name":"Aeroplane mode…"}'


def test_a_refusal_is_not_delivered_and_safe_to_retry():
    refused = Refused.of(Refusal(ErrorCode.DEVICE_AMBIGUOUS, "Several.", {"devices": ["a", "b"]}))
    wire = to_wire("snapshot", None, refused)
    assert wire["ok"] is False and wire["delivery"] == "not_delivered" and wire["retry"] == "safe"
    assert wire["error"] == {
        "code": "DEVICE_AMBIGUOUS",
        "message": "Several.",
        "hint": HINTS[ErrorCode.DEVICE_AMBIGUOUS],
        "details": {"devices": ["a", "b"]},
    }
    assert "data" not in wire


def test_a_code_with_no_hint_prints_a_null_hint():
    wire = to_wire("snapshot", None, Refused(ErrorCode.NO_SURFACE, "Screen off."))
    assert wire["error"]["hint"] is None


def test_exit_codes_are_zero_for_a_read_one_for_an_error_and_two_for_bad_arguments():
    assert exit_code(Read(ServerStatus(False, False, None, None))) == 0
    assert exit_code(Refused(ErrorCode.NO_DEVICE, "none")) == 1
    assert exit_code(Refused(ErrorCode.INVALID_ARGS, "bad")) == 2


@pytest.mark.parametrize(
    ("unrefunded", "delivery", "retry"),
    [(False, "not_delivered", "safe"), (True, "delivery_uncertain", "unsafe")],
)
def test_an_uncaught_exception_is_internal_and_asks_the_ledger_how_far_input_got(unrefunded, delivery, retry):
    wire = floor_envelope("click", J7.serial, ValueError("boom"), unrefunded)
    assert (wire["delivery"], wire["retry"]) == (delivery, retry)
    assert wire["error"]["code"] == "INTERNAL" and "ValueError: boom" in wire["error"]["message"]
    json.loads(encode(wire))


def test_a_device_row_has_facts_only_when_they_were_read():
    rows = DeviceList(
        (
            Listed(Connected(J7.serial, "SM_J730F", True), INFO, None, None),
            Listed(Connected(Serial("R58M1234567"), "", False), None, None, None),
            Listed(Connected(Serial("emulator-5554"), "emu", True), None, "adb timed out.", None),
        )
    )
    first, second, third = to_wire("devices", None, Read(rows))["data"]["devices"]
    assert first["model"] == "SM-J730F" and first["display"] == [1080, 1920] and first["ime"] == "ime.pkg"
    assert second == {"serial": "R58M1234567", "model": "", "ready": False, "profile": None}
    assert third["problem"] == "adb timed out." and "api" not in third


def acted(sent, error=None):
    address = NodeAddress(Package("com.android.settings"), "", "", "", "", Rect(0, 910, 1920, 1080), (), None)
    tap = Tap(Point(960, 995), address)
    target = TargetReport("@q7m2k:e7", Role.BUTTON, "Display", Point(960, 995))
    report = ActionReport(tap, target, Clear(ClearReason.NO_COMMIT_WORDS), None)
    return Acted(sent, report, None, error, "late" if error else "")


def test_an_input_that_went_out_says_what_was_sent_and_is_never_safe_to_retry():
    wire = to_wire("click", J7.serial, acted(SentState.UNVERIFIED))
    assert (wire["ok"], wire["delivery"], wire["retry"]) == (True, "delivered_unverified", "unsafe")
    assert wire["data"] == {
        "input": {"kind": "tap", "at": [960, 995]},
        "target": {"ref": "@q7m2k:e7", "role": "button", "name": "Display", "at": [960, 995]},
        "gate": {"verdict": "clear", "reason": "no_commit_words"},
        "verified_by": None,
        "after": None,
    }
    assert "error" not in wire and exit_code(acted(SentState.UNVERIFIED)) == 0


def test_an_input_that_went_out_and_then_failed_keeps_its_delivery_and_adds_the_error():
    late = acted(SentState.UNCERTAIN, ErrorCode.TIMEOUT)
    wire = to_wire("click", J7.serial, late)
    assert (wire["ok"], wire["delivery"], wire["retry"]) == (False, "delivery_uncertain", "unsafe")
    assert wire["error"]["code"] == "TIMEOUT" and wire["data"]["input"]["kind"] == "tap"
    assert exit_code(late) == 1
