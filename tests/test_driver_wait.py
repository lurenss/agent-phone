"""`Driver.wait`: the public API door to the `wait` command, through `agent_phone` only."""

import pytest
from fakes import J7_SERIAL, FakeHub
from support import FakeClock, fixture_screen, node, screen_of

from agent_phone import (
    Foreground,
    Gone,
    KeyName,
    Package,
    PhoneError,
    Present,
    Q,
    Settled,
    Snapshot,
    open_phone,
)
from agent_phone.cli.settings import Settings
from agent_phone.core.commands.wait import WAIT_TIMEOUT_MS
from agent_phone.core.device import Connected
from agent_phone.core.outcome import Disposition, ErrorCode, Refused, disposition_of
from agent_phone.core.refs.store import SnapshotStore

J7 = Connected(J7_SERIAL, "SM_J730F", ready=True)
SETTINGS = fixture_screen("settings-home")
BRIGHTNESS = screen_of(
    node(
        "android.widget.FrameLayout",
        node("android.widget.TextView", text="Brightness", bounds="[0,200][1080,300]"),
        package="com.android.settings",
        bounds="[0,0][1080,1920]",
    )
)


def session(hub, tmp_path, clock=None):
    settings = Settings(state_root=tmp_path, lock_wait_s=0.0)
    return open_phone(hub=hub, settings=settings, clock=clock or FakeClock())


def test_wait_returns_the_snapshot_of_the_read_the_condition_held_on(tmp_path):
    hub = FakeHub([J7], screens=[SETTINGS, SETTINGS, BRIGHTNESS])
    with session(hub, tmp_path) as phone:
        seen = phone.wait(Present(Q("Brightness")))
    assert isinstance(seen, Snapshot) and [line.name for line in seen.lines] == ["Brightness"]
    assert hub.phones[0].reads == 3 and hub.phones[0].permits == []
    assert SnapshotStore(tmp_path).latest(J7_SERIAL) == seen


def test_wait_takes_one_condition_or_a_sequence_of_them(tmp_path):
    hub = FakeHub([J7], screens=[SETTINGS])
    with session(hub, tmp_path) as phone:
        one = phone.wait(Foreground(Package("com.android.settings")))
        several = phone.wait([Present(Q("Display")), Gone(Q("Brightness")), Settled()])
    assert one.package == several.package == "com.android.settings"
    assert one.settled.value == "unchecked" and several.settled.value == "settled"


def test_a_wait_that_times_out_raises_with_the_last_read_in_its_outcome(tmp_path):
    hub = FakeHub([J7], screens=[SETTINGS])
    with session(hub, tmp_path) as phone, pytest.raises(PhoneError) as raised:
        phone.wait(Present(Q("Brightness")), timeout_ms=300)
    outcome = raised.value.outcome
    assert isinstance(outcome, Refused) and outcome.code is ErrorCode.TIMEOUT
    assert disposition_of(outcome) is Disposition.NOT_DELIVERED and disposition_of(outcome).retry_safe
    after = outcome.details["after"]
    assert isinstance(after, Snapshot) and after.package == "com.android.settings"
    assert hub.phones[0].permits == []


def test_the_default_timeout_is_the_commands(tmp_path):
    clock = FakeClock()
    hub = FakeHub([J7], screens=[SETTINGS])
    with session(hub, tmp_path, clock) as phone, pytest.raises(PhoneError):
        phone.wait(Present(Q("Brightness")))
    assert WAIT_TIMEOUT_MS / 1000 <= clock.time < WAIT_TIMEOUT_MS / 1000 + 1


def test_a_wait_with_no_condition_raises_invalid_args_and_reads_nothing(tmp_path):
    hub = FakeHub([J7], screens=[SETTINGS])
    with session(hub, tmp_path) as phone, pytest.raises(PhoneError) as raised:
        phone.wait(())
    assert isinstance(raised.value.outcome, Refused)
    assert raised.value.outcome.code is ErrorCode.INVALID_ARGS and hub.phones[0].reads == 0


def test_a_wait_after_an_input_gives_the_next_input_its_observation(tmp_path):
    hub = FakeHub([J7], screens=[SETTINGS], after_input=[BRIGHTNESS])
    with session(hub, tmp_path) as phone:
        phone.snapshot()
        phone.launch("com.android.settings")
        with pytest.raises(PhoneError) as blind:
            phone.press(KeyName.BACK)
        assert blind.value.outcome.code is ErrorCode.OBSERVE_FIRST
        seen = phone.wait(Present(Q("Brightness")))
        phone.press(KeyName.BACK)
    assert seen.epoch == 1 and len(hub.phones[0].permits) == 2
