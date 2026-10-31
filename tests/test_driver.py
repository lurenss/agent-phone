import json

import pytest
from fakes import EMULATOR_SERIAL, J7_BOOT, J7_SERIAL, FakeHub
from support import GOLDEN, FakeClock, fixture_screen, snapshot_of

from agent_phone.cli.driver import PhoneError, open_phone
from agent_phone.cli.settings import Settings
from agent_phone.core.device import Connected, DeviceIdentity
from agent_phone.core.outcome import ErrorCode, Refusal, Refused
from agent_phone.core.refs.store import SnapshotStore

J7 = Connected(J7_SERIAL, "SM_J730F", ready=True)
EMULATOR = Connected(EMULATOR_SERIAL, "emu", ready=True)
IDENTITY = DeviceIdentity(J7_SERIAL, J7_BOOT)


@pytest.fixture
def settings(tmp_path):
    return Settings(state_root=tmp_path, lock_wait_s=0.0)


def session(hub, settings, **kwargs):
    return open_phone(hub=hub, settings=settings, clock=FakeClock(), **kwargs)


def refusal_of(error: pytest.ExceptionInfo[PhoneError]) -> Refused:
    assert isinstance(error.value.outcome, Refused)
    return error.value.outcome


def test_a_snapshot_is_what_capture_makes_of_the_screen_and_is_recorded_on_disk(settings):
    screen = fixture_screen("settings-home")
    hub = FakeHub([J7], screens=[screen])
    with session(hub, settings) as phone:
        taken = phone.snapshot()
    assert taken == snapshot_of(screen, taken.id, IDENTITY, epoch=0)
    store = SnapshotStore(settings.state_root)
    assert store.load(taken.id) == taken and store.latest(J7_SERIAL) == taken


def test_a_snapshot_carries_the_ledger_epoch_of_this_boot_and_restarts_after_another(settings):
    ledger = settings.state_root / "devices" / J7_SERIAL / "ledger.json"
    ledger.parent.mkdir(parents=True)
    screen = fixture_screen("settings-home")
    ledger.write_text(json.dumps({"boot_id": J7_BOOT, "epoch": 7}))
    with session(FakeHub([J7], screens=[screen]), settings) as phone:
        assert phone.snapshot().epoch == 7
    ledger.write_text(json.dumps({"boot_id": "an-earlier-boot", "epoch": 7}))
    with session(FakeHub([J7], screens=[screen]), settings) as phone:
        assert phone.snapshot().epoch == 0


def test_a_ledger_that_cannot_be_read_refuses_instead_of_restarting_at_zero(settings):
    ledger = settings.state_root / "devices" / J7_SERIAL / "ledger.json"
    ledger.parent.mkdir(parents=True)
    ledger.write_text("{not json")
    with session(FakeHub([J7], screens=[fixture_screen("settings-home")]), settings) as phone:
        with pytest.raises(PhoneError) as raised:
            phone.snapshot()
    assert refusal_of(raised).code is ErrorCode.INTERNAL and "Delete it" in refusal_of(raised).message


def test_a_session_holds_the_device_lock_and_closes_the_phone(settings):
    hub = FakeHub([J7], screens=[fixture_screen("settings-home")])
    with session(hub, settings):
        with pytest.raises(PhoneError) as raised, session(hub, settings):
            pass
        assert refusal_of(raised).code is ErrorCode.DEVICE_BUSY
        assert len(hub.phones) == 1, "the second session never reached the device"
    assert hub.phones[0].closed
    with session(hub, settings):
        pass


def test_the_lock_is_per_device(settings):
    hub = FakeHub([J7, EMULATOR], screens=[fixture_screen("settings-home")])
    with session(hub, settings, serial=J7_SERIAL), session(hub, settings, serial=EMULATOR_SERIAL):
        pass


@pytest.mark.parametrize(
    ("connected", "serial", "code"),
    [
        ([J7, EMULATOR], None, ErrorCode.DEVICE_AMBIGUOUS),
        ([J7], "nope", ErrorCode.NO_DEVICE),
        ([], None, ErrorCode.NO_DEVICE),
    ],
)
def test_a_device_that_cannot_be_chosen_never_gets_opened_or_locked(settings, connected, serial, code):
    hub = FakeHub(connected)
    with pytest.raises(PhoneError) as raised, session(hub, settings, serial=serial):
        pass
    assert refusal_of(raised).code is code
    assert hub.phones == [] and not (settings.state_root / "devices").exists()


def test_a_device_that_will_not_open_leaves_the_lock_free(settings):
    hub = FakeHub([J7], open_problem=Refusal(ErrorCode.SERVER_UNAVAILABLE, "no server"))
    with pytest.raises(PhoneError) as raised, session(hub, settings):
        pass
    assert refusal_of(raised).code is ErrorCode.SERVER_UNAVAILABLE
    with SnapshotStore(settings.state_root).lock(J7_SERIAL, FakeClock(), 0):
        pass


def test_a_screen_that_cannot_be_read_is_a_refusal_the_caller_can_catch(settings):
    hub = FakeHub([J7], screens=[Refusal(ErrorCode.NO_SURFACE, "The screen may be off.")])
    with session(hub, settings) as phone, pytest.raises(PhoneError) as raised:
        phone.snapshot()
    assert refusal_of(raised).code is ErrorCode.NO_SURFACE


def test_settle_and_root_wait_for_unit_three(settings):
    hub = FakeHub([J7], screens=[fixture_screen("settings-home")])
    with session(hub, settings) as phone, pytest.raises(PhoneError) as raised:
        phone.snapshot(settle=True)
    assert refusal_of(raised).code is ErrorCode.NOT_SUPPORTED


def test_a_caller_policy_file_is_read_and_a_bad_one_is_refused_at_open(settings, tmp_path):
    good = tmp_path / "good.toml"
    good.write_text('languages = ["en"]\n')
    bad = tmp_path / "bad.toml"
    bad.write_text("[[commit]]\nid = ")
    hub = FakeHub([J7], screens=[fixture_screen("settings-home")])
    with session(hub, settings, policies=[good]):
        pass
    with pytest.raises(PhoneError) as raised, session(hub, settings, policies=[bad]):
        pass
    assert refusal_of(raised).code is ErrorCode.POLICY_INVALID and str(bad) in refusal_of(raised).message


def test_the_state_root_argument_wins_over_the_settings(settings, tmp_path):
    elsewhere = tmp_path / "elsewhere"
    hub = FakeHub([J7], screens=[fixture_screen("settings-home")])
    with open_phone(state_root=elsewhere, hub=hub, settings=settings, clock=FakeClock()) as phone:
        phone.snapshot()
    assert (elsewhere / "devices" / J7_SERIAL / "latest").exists()
    assert not (settings.state_root / "devices" / J7_SERIAL / "latest").exists()


def test_the_cli_prints_the_golden_lines_for_a_snapshot_and_names_the_device(settings):
    import io

    from agent_phone.cli.process import run

    hub = FakeHub([J7], screens=[fixture_screen("settings-home")])
    out = io.StringIO()
    assert run(["snapshot"], hub, settings, out, FakeClock()) == 0
    wire = json.loads(out.getvalue())
    assert wire["device"] == J7_SERIAL and wire["command"] == "snapshot"
    golden = (GOLDEN / "settings-home.compact.txt").read_text().splitlines()
    assert [line.replace(f"@{wire['data']['id']}:", "@t0000:") for line in wire["data"]["tree"]] == golden
    assert (settings.state_root / "devices" / J7_SERIAL / "snapshots" / f"{wire['data']['id']}.json").exists()


def test_the_cli_reports_a_busy_device_without_reading_it(settings):
    import io

    from agent_phone.cli.process import run

    hub = FakeHub([J7], screens=[fixture_screen("settings-home")])
    out = io.StringIO()
    with SnapshotStore(settings.state_root).lock(J7_SERIAL, FakeClock(), 0, "snapshot"):
        assert run(["snapshot"], hub, settings, out, FakeClock()) == 1
    wire = json.loads(out.getvalue())
    assert wire["error"]["code"] == "DEVICE_BUSY" and wire["delivery"] == "not_delivered"
    assert wire["device"] == J7_SERIAL, "a device was chosen, so the envelope names it"
    assert hub.phones == []
