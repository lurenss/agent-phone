import json

import pytest
from fakes import EMULATOR_SERIAL, J7_BOOT, J7_SERIAL, FakeHub, invoke
from support import fixture_screen

from agent_phone.core.device import Connected

J7 = Connected(J7_SERIAL, "SM_J730F", ready=True)
EMULATOR = Connected(EMULATOR_SERIAL, "emu", ready=True)


def first_snapshot(tmp_path, name="settings-home", hub=None):
    hub = hub or FakeHub([J7], screens=[fixture_screen(name)])
    code, wire = invoke(["snapshot"], hub, tmp_path)
    assert code == 0
    return hub, wire["data"]


def test_a_drill_down_is_a_new_snapshot_of_the_subtree_with_the_same_ref_numbers(tmp_path):
    hub, whole = first_snapshot(tmp_path)
    code, drilled = invoke(["snapshot", "--root", f"@{whole['id']}:e3"], hub, tmp_path)
    data = drilled["data"]
    assert code == 0 and data["id"] != whole["id"]
    numbers = [line.split()[0].split(":")[1] for line in data["tree"] if line.lstrip().startswith("@")]
    assert numbers == ["e3", "e4", "e5", "e6", "e7"]
    assert data["tree"][0].startswith(f"@{data['id']}:e3 list #dashboard_container (4 rows)")
    assert "Search" not in "".join(data["tree"])


def test_the_snapshot_that_held_the_ref_stays_valid_after_a_drill_down(tmp_path):
    hub, whole = first_snapshot(tmp_path)
    ref = f"@{whole['id']}:e3"
    assert invoke(["snapshot", "--root", ref], hub, tmp_path)[0] == 0
    assert invoke(["snapshot", "--root", ref], hub, tmp_path)[0] == 0


def test_a_drill_down_ref_drills_again_into_a_smaller_subtree(tmp_path):
    hub, whole = first_snapshot(tmp_path)
    _, drilled = invoke(["snapshot", "--root", f"@{whole['id']}:e3"], hub, tmp_path)
    code, again = invoke(["snapshot", "--root", f"@{drilled['data']['id']}:e4"], hub, tmp_path)
    assert code == 0 and [line.split()[0].split(":")[1] for line in again["data"]["tree"][:1]] == ["e4"]


def test_a_drill_down_takes_the_mode_and_settle_flags(tmp_path):
    hub, whole = first_snapshot(tmp_path)
    ref = f"@{whole['id']}:e3"
    code, wire = invoke(["snapshot", "--root", ref, "--skeleton", "--settle"], hub, tmp_path)
    assert code == 0 and wire["data"]["mode"] == "skeleton" and wire["data"]["settled"] == "settled"
    assert wire["data"]["tree"][0].endswith("(4 rows) (+4) [0,179,1920,1080]")


def test_a_drill_down_on_an_element_that_left_the_screen_is_stale_and_says_gone(tmp_path):
    _, whole = first_snapshot(tmp_path)
    elsewhere = FakeHub([J7], screens=[fixture_screen("ig-feed")])
    code, wire = invoke(["snapshot", "--root", f"@{whole['id']}:e3"], elsewhere, tmp_path)
    assert (
        code == 1 and wire["error"]["code"] == "STALE_REF" and wire["error"]["details"] == {"reason": "gone"}
    )
    assert elsewhere.phones[0].reads == 1
    assert (wire["delivery"], wire["retry"]) == ("not_delivered", "safe")


def test_a_drill_down_after_input_was_sent_is_stale_before_the_screen_is_read(tmp_path):
    hub, whole = first_snapshot(tmp_path)
    ledger = tmp_path / "devices" / J7_SERIAL / "ledger.json"
    ledger.write_text(json.dumps({"boot_id": J7_BOOT, "epoch": 1}))
    code, wire = invoke(["snapshot", "--root", f"@{whole['id']}:e3"], hub, tmp_path)
    assert code == 1 and wire["error"]["details"] == {"reason": "spent"}
    assert len(hub.phones) == 2 and hub.phones[1].reads == 0


@pytest.mark.parametrize(
    ("ref", "code"),
    [("@zzzzz:e1", "SNAPSHOT_NOT_FOUND"), ("e3", "INVALID_ARGS"), ("@zzzzz:3", "INVALID_ARGS")],
)
def test_a_ref_that_was_never_printed_or_is_not_a_ref_is_refused(tmp_path, ref, code):
    exit_code, wire = invoke(
        ["snapshot", "--root", ref], FakeHub([J7], screens=[fixture_screen("settings-home")]), tmp_path
    )
    assert exit_code in (1, 2) and wire["error"]["code"] == code


def test_a_ref_that_is_not_in_its_snapshot_is_not_found(tmp_path):
    hub, whole = first_snapshot(tmp_path)
    code, wire = invoke(["snapshot", "--root", f"@{whole['id']}:e99"], hub, tmp_path)
    assert code == 1 and wire["error"]["code"] == "NOT_FOUND"


def test_the_ref_names_its_device_so_no_dash_d_is_needed_and_a_wrong_one_is_refused(tmp_path):
    hub = FakeHub([J7, EMULATOR], screens=[fixture_screen("settings-home")])
    code, whole = invoke(["-d", J7_SERIAL, "snapshot"], hub, tmp_path)
    ref = f"@{whole['data']['id']}:e3"
    code, wire = invoke(["snapshot", "--root", ref], hub, tmp_path)
    assert code == 0 and wire["device"] == J7_SERIAL
    code, wire = invoke(["-d", EMULATOR_SERIAL, "snapshot", "--root", ref], hub, tmp_path)
    assert code == 1 and wire["error"]["code"] == "WRONG_DEVICE"


@pytest.mark.parametrize("flag", [["--surface", "dialog"], ["--window", "0"]])
def test_a_root_cannot_be_combined_with_a_surface_or_a_window(tmp_path, flag):
    hub, whole = first_snapshot(tmp_path)
    code, wire = invoke(["snapshot", "--root", f"@{whole['id']}:e3", *flag], hub, tmp_path)
    assert code == 2 and wire["error"]["code"] == "INVALID_ARGS"
