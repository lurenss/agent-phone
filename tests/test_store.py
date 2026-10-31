import dataclasses

import pytest
from support import FIXTURES, fixture_screen, node, screen_of, snapshot_of

from agent_phone.core.device import BootId, DeviceIdentity, Serial
from agent_phone.core.outcome import ErrorCode, Refusal
from agent_phone.core.refs.store import RETAINED_PER_DEVICE, SnapshotStore
from agent_phone.core.snapshot.snapshot import SnapshotId

J7 = DeviceIdentity(Serial("0a1b2c3d4e5f6a7b"), BootId("8d3f6c1e-0b5a-4c2e-9f1d-2a7b3c4d5e6f"))
EMULATOR = DeviceIdentity(Serial("emulator-5554"), BootId("0c1d2e3f-4a5b-6c7d-8e9f-0a1b2c3d4e5f"))


@pytest.mark.parametrize("name", FIXTURES)
def test_a_recorded_snapshot_reads_back_equal(tmp_path, name):
    store = SnapshotStore(tmp_path)
    snapshot = snapshot_of(fixture_screen(name), store.new_id(J7.serial), J7, epoch=7)
    store.record(snapshot)
    assert store.load(snapshot.id) == snapshot
    assert SnapshotStore(tmp_path).latest(J7.serial) == snapshot


def test_twins_secrets_and_values_survive_the_round_trip(tmp_path):
    icon = "android.widget.ImageView"
    screen = screen_of(
        node(
            "android.widget.FrameLayout",
            node(icon, clickable=True, bounds="[0,0][100,100]"),
            node(icon, clickable=True, bounds="[100,0][200,100]"),
            node("android.widget.EditText", hint="Password", password=True, clickable=True, focused=True),
            node("android.widget.SeekBar", text="40", content_desc="Volume"),
        )
    )
    store = SnapshotStore(tmp_path)
    snapshot = snapshot_of(screen, store.new_id(J7.serial), J7)
    assert any(fp.twin for fp in snapshot.fingerprints.values())
    store.record(snapshot)
    assert store.load(snapshot.id) == snapshot


def test_a_snapshot_names_the_device_that_took_it(tmp_path):
    store = SnapshotStore(tmp_path)
    mine = snapshot_of(fixture_screen("settings-home"), store.new_id(J7.serial), J7)
    theirs = snapshot_of(fixture_screen("settings-home"), store.new_id(EMULATOR.serial), EMULATOR)
    store.record(mine)
    store.record(theirs)
    assert (store.device_of(mine.id), store.device_of(theirs.id)) == (J7.serial, EMULATOR.serial)
    assert store.device_of(SnapshotId("zzzzz")) is None
    assert store.latest(J7.serial) == mine and store.latest(EMULATOR.serial) == theirs


def test_an_unknown_or_unreadable_snapshot_is_not_found(tmp_path):
    store = SnapshotStore(tmp_path)
    with pytest.raises(Refusal) as missing:
        store.load(SnapshotId("zzzzz"))
    snapshot = snapshot_of(fixture_screen("settings-home"), store.new_id(J7.serial), J7)
    store.record(snapshot)
    (tmp_path / "devices" / J7.serial / "snapshots" / f"{snapshot.id}.json").write_text('{"format": 0}')
    with pytest.raises(Refusal) as unreadable:
        store.load(snapshot.id)
    assert missing.value.code is unreadable.value.code is ErrorCode.SNAPSHOT_NOT_FOUND
    assert store.latest(Serial("emulator-5556")) is None


def test_recording_the_same_snapshot_twice_is_a_no_op_and_a_clash_is_refused(tmp_path):
    store = SnapshotStore(tmp_path)
    snapshot = snapshot_of(fixture_screen("settings-home"), store.new_id(J7.serial), J7)
    store.record(snapshot)
    store.record(snapshot)
    assert store.load(snapshot.id) == snapshot
    with pytest.raises(Refusal) as clash:
        store.record(dataclasses.replace(snapshot, epoch=snapshot.epoch + 1))
    assert clash.value.code is ErrorCode.INTERNAL
    with pytest.raises(Refusal):
        store.record(dataclasses.replace(snapshot, device=EMULATOR))


def test_each_device_keeps_only_its_newest_snapshots(tmp_path):
    store = SnapshotStore(tmp_path)
    screen = fixture_screen("settings-home")
    ids = []
    for _ in range(RETAINED_PER_DEVICE + 2):
        snapshot = snapshot_of(screen, store.new_id(J7.serial), J7)
        store.record(snapshot)
        ids.append(snapshot.id)
    kept = list((tmp_path / "devices" / J7.serial / "snapshots").glob("*.json"))
    assert len(kept) == RETAINED_PER_DEVICE
    assert store.load(ids[-1]).id == ids[-1] and store.latest(J7.serial).id == ids[-1]
