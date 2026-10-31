import json

import pytest
from fakes import EMULATOR_SERIAL, J7_BOOT, J7_SERIAL, FakeHub, invoke
from support import FakeClock, fixture_screen, node, screen_of

from agent_phone.cli.driver import PhoneError, open_phone
from agent_phone.cli.settings import Settings
from agent_phone.core.commands.get import GetProperty
from agent_phone.core.commands.is_ import IsProperty
from agent_phone.core.device import Connected
from agent_phone.core.refs.store import SnapshotStore

J7 = Connected(J7_SERIAL, "SM_J730F", ready=True)
EMULATOR = Connected(EMULATOR_SERIAL, "emu", ready=True)


def controls(checked=False, enabled=True, text="lorenzo"):
    return screen_of(
        node(
            "android.widget.FrameLayout",
            node(
                "android.widget.Switch",
                text="Wi-Fi",
                checkable=True,
                checked=checked,
                bounds="[0,0][400,100]",
            ),
            node(
                "android.widget.Button",
                text="Save",
                clickable=True,
                enabled=enabled,
                bounds="[0,100][400,200]",
            ),
            node(
                "android.widget.EditText",
                text=text,
                hint="Name",
                clickable=True,
                focused=True,
                bounds="[0,200][400,300]",
            ),
            node(
                "android.widget.EditText",
                text="hunter2",
                hint="Password",
                clickable=True,
                password=True,
                bounds="[0,300][400,400]",
            ),
        )
    )


def taken(tmp_path, screen):
    """A snapshot of `screen` on disk, and the ref of each of its numbered elements."""
    hub = FakeHub([J7], screens=[screen])
    code, wire = invoke(["snapshot"], hub, tmp_path)
    assert code == 0
    return wire["data"]["id"]


def read(command, ref, tmp_path, screen, *flags):
    return invoke([command, ref, *flags], FakeHub([J7], screens=[screen]), tmp_path)


def test_get_text_is_the_name_and_the_detail_a_person_reads(tmp_path):
    settings = fixture_screen("settings-home")
    id = taken(tmp_path, settings)
    code, wire = read("get", f"@{id}:e4", tmp_path, settings)
    assert code == 0 and wire["device"] == J7_SERIAL
    assert wire["data"] == {
        "ref": f"@{id}:e4",
        "property": "text",
        "value": "Connections, Wi-Fi, Bluetooth, Data usage, Airplane mode",
    }


def test_get_bounds_and_states_come_from_the_live_screen(tmp_path):
    settings = fixture_screen("settings-home")
    id = taken(tmp_path, settings)
    assert read("get", f"@{id}:e4", tmp_path, settings, "--property", "bounds")[1]["data"]["value"] == [
        0,
        179,
        1920,
        394,
    ]
    assert read("get", f"@{id}:e4", tmp_path, settings, "--property", "states")[1]["data"]["value"] == [
        "focused"
    ]


def test_a_value_is_what_is_typed_and_a_button_has_none(tmp_path):
    screen = controls()
    id = taken(tmp_path, screen)
    assert read("get", f"@{id}:e3", tmp_path, screen, "--property", "value")[1]["data"]["value"] == "lorenzo"
    assert read("get", f"@{id}:e2", tmp_path, screen, "--property", "value")[1]["data"]["value"] is None
    assert read("get", f"@{id}:e3", tmp_path, screen)[1]["data"]["value"] == "lorenzo"


def test_a_secret_field_never_gives_its_text_or_its_value(tmp_path):
    screen = controls()
    id = taken(tmp_path, screen)
    for flags in ([], ["--property", "value"], ["--property", "states"]):
        code, wire = read("get", f"@{id}:e4", tmp_path, screen, *flags)
        assert code == 0 and "hunter2" not in json.dumps(wire)
    assert read("get", f"@{id}:e4", tmp_path, screen)[1]["data"]["value"] == "Password"
    assert read("get", f"@{id}:e4", tmp_path, screen, "--property", "value")[1]["data"]["value"] is None
    assert "secret" in read("get", f"@{id}:e4", tmp_path, screen, "--property", "states")[1]["data"]["value"]


@pytest.mark.parametrize(
    ("number", "prop", "result"),
    [
        (1, "checked", False),
        (1, "enabled", True),
        (1, "visible", True),
        (2, "enabled", False),
        (3, "focused", True),
        (2, "selected", False),
        (2, "checked", False),
    ],
)
def test_is_reads_one_boolean_from_the_live_screen(tmp_path, number, prop, result):
    before = controls(enabled=False)
    id = taken(tmp_path, before)
    code, wire = read("is", f"@{id}:e{number}", tmp_path, before, "--property", prop)
    assert code == 0 and wire["data"]["property"] == prop and wire["data"]["value"] is result


def test_is_answers_for_the_screen_as_it_is_now_not_as_it_was_printed(tmp_path):
    id = taken(tmp_path, controls(checked=False))
    code, wire = read("is", f"@{id}:e1", tmp_path, controls(checked=True), "--property", "checked")
    assert code == 0 and wire["data"]["value"] is True
    code, wire = read("is", f"@{id}:e1", tmp_path, controls(checked=False), "--property", "checked")
    assert wire["data"]["value"] is False


def test_is_visible_is_the_default_property(tmp_path):
    screen = controls()
    id = taken(tmp_path, screen)
    assert read("is", f"@{id}:e1", tmp_path, screen)[1]["data"]["property"] == "visible"


def test_an_element_that_left_the_screen_is_stale_gone_for_get_and_is(tmp_path):
    id = taken(tmp_path, controls())
    for command in ("get", "is"):
        code, wire = read(command, f"@{id}:e1", tmp_path, fixture_screen("ig-feed"))
        assert (
            code == 1
            and wire["error"]["code"] == "STALE_REF"
            and wire["error"]["details"] == {"reason": "gone"}
        )
        assert (wire["delivery"], wire["retry"]) == ("not_delivered", "safe")


def test_a_ref_spent_by_input_is_refused_before_the_phone_is_read(tmp_path):
    screen = controls()
    id = taken(tmp_path, screen)
    (tmp_path / "devices" / J7_SERIAL / "ledger.json").write_text(
        json.dumps({"boot_id": J7_BOOT, "epoch": 1})
    )
    hub = FakeHub([J7], screens=[screen])
    code, wire = invoke(["get", f"@{id}:e1"], hub, tmp_path)
    assert code == 1 and wire["error"]["details"] == {"reason": "spent"} and hub.phones[0].reads == 0


def test_a_ref_that_is_not_in_its_snapshot_or_not_a_ref_is_refused(tmp_path):
    screen = controls()
    id = taken(tmp_path, screen)
    assert read("get", f"@{id}:e99", tmp_path, screen)[1]["error"]["code"] == "NOT_FOUND"
    assert read("get", "@zzzzz:e1", tmp_path, screen)[1]["error"]["code"] == "SNAPSHOT_NOT_FOUND"
    code, wire = read("is", "e1", tmp_path, screen)
    assert code == 2 and wire["error"]["code"] == "INVALID_ARGS"


@pytest.mark.parametrize(
    "argv", [["get", "@zzzzz:e1", "--property", "colour"], ["is", "@zzzzz:e1", "--property", "text"], ["get"]]
)
def test_an_unknown_property_or_a_missing_ref_is_invalid_args(tmp_path, argv):
    code, wire = invoke(argv, FakeHub([J7], screens=[controls()]), tmp_path)
    assert code == 2 and wire["error"]["code"] == "INVALID_ARGS"


def test_the_ref_names_its_device_and_a_wrong_dash_d_is_refused(tmp_path):
    screen = controls()
    hub = FakeHub([J7, EMULATOR], screens=[screen])
    _, wire = invoke(["-d", J7_SERIAL, "snapshot"], hub, tmp_path)
    ref = f"@{wire['data']['id']}:e1"
    code, wire = invoke(["is", ref], hub, tmp_path)
    assert code == 0 and wire["device"] == J7_SERIAL
    code, wire = invoke(["is", ref, "-d", EMULATOR_SERIAL], hub, tmp_path)
    assert code == 1 and wire["error"]["code"] == "WRONG_DEVICE"


def test_get_and_is_record_no_snapshot_and_change_no_ref(tmp_path):
    screen = controls()
    id = taken(tmp_path, screen)
    store = SnapshotStore(tmp_path)
    assert store.latest(J7_SERIAL).id == id
    read("get", f"@{id}:e1", tmp_path, screen)
    read("is", f"@{id}:e1", tmp_path, screen)
    assert store.latest(J7_SERIAL).id == id
    assert len(list((tmp_path / "devices" / J7_SERIAL / "snapshots").glob("*.json"))) == 1


def test_the_driver_gets_and_checks_a_ref(tmp_path):
    screen = controls()
    hub = FakeHub([J7], screens=[screen])
    settings = Settings(state_root=tmp_path, lock_wait_s=0.0)
    with open_phone(hub=hub, settings=settings, clock=FakeClock()) as phone:
        whole = phone.snapshot()
        assert phone.get(whole.ref(3), GetProperty.VALUE) == "lorenzo"
        assert phone.get(whole.ref(1), GetProperty.BOUNDS) == (0, 0, 400, 100)
        assert phone.is_(whole.ref(3), IsProperty.FOCUSED) is True
        with pytest.raises(PhoneError) as raised:
            phone.is_(whole.ref(99))
        assert raised.value.outcome.code.value == "NOT_FOUND"
