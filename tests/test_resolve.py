import pytest
from fakes import J7_BOOT, J7_SERIAL
from support import consumer_of, fixture_screen, labelled, node, screen_of, snapshot_of

from agent_phone.core.device import BootId, DeviceIdentity, Serial
from agent_phone.core.outcome import ErrorCode, Refusal
from agent_phone.core.refs.resolve import RefTarget, locate, observed_snapshot
from agent_phone.core.refs.store import SnapshotStore
from agent_phone.core.snapshot.snapshot import RefToken, SnapshotId

ID = SnapshotId("k3x9q")
DEVICE = DeviceIdentity(J7_SERIAL, J7_BOOT)


def ref(number, snapshot=ID):
    return RefTarget(RefToken(snapshot, number))


def refused(call):
    with pytest.raises(Refusal) as raised:
        call()
    return raised.value


def buttons(*bounds, label="Mute"):
    return screen_of(
        node(
            "android.widget.FrameLayout",
            *(node("android.widget.ImageView", content_desc=label, clickable=True, bounds=b) for b in bounds),
        )
    )


def test_a_ref_finds_its_element_on_a_screen_that_shows_it_somewhere_else():
    before, after = buttons("[0,0][100,100]"), buttons("[0,500][100,600]")
    resolved = locate(ref(1), snapshot_of(before, ID, DEVICE), after)
    assert after.node(resolved.node).attrs.bounds.top == 500


def test_a_ref_finds_the_settings_tile_it_was_taken_from():
    settings = fixture_screen("settings-home")
    tile = consumer_of(settings, labelled(settings, "Display"))
    resolved = locate(ref(7), snapshot_of(settings, ID, DEVICE), settings)
    assert resolved.node == tile.id


def test_an_element_that_left_the_screen_is_stale_with_the_reason_gone():
    taken = snapshot_of(buttons("[0,0][100,100]"), ID, DEVICE)
    renamed = buttons("[0,0][100,100]", label="Unmute")
    error = refused(lambda: locate(ref(1), taken, renamed))
    assert error.code is ErrorCode.STALE_REF and error.details == {"reason": "gone"}


def test_a_ref_number_that_the_snapshot_never_printed_is_not_found():
    taken = snapshot_of(buttons("[0,0][100,100]"), ID, DEVICE)
    error = refused(lambda: locate(ref(9), taken, buttons("[0,0][100,100]")))
    assert error.code is ErrorCode.NOT_FOUND and "e9" in error.message


def test_a_new_element_with_the_same_key_makes_the_ref_ambiguous():
    taken = snapshot_of(buttons("[0,0][100,100]"), ID, DEVICE)
    error = refused(lambda: locate(ref(1), taken, buttons("[0,0][100,100]", "[0,200][100,300]")))
    assert error.code is ErrorCode.AMBIGUOUS_TARGET and error.details == {"matches": 2}


def test_twins_resolve_by_position_only_while_the_whole_set_has_not_moved():
    twins = buttons("[0,0][100,100]", "[0,200][100,300]")
    taken = snapshot_of(twins, ID, DEVICE)
    assert twins.node(locate(ref(2), taken, twins).node).attrs.bounds.top == 200
    shifted = buttons("[0,0][100,100]", "[0,250][100,350]")
    assert refused(lambda: locate(ref(2), taken, shifted)).code is ErrorCode.AMBIGUOUS_TARGET
    fewer = buttons("[0,0][100,100]")
    assert refused(lambda: locate(ref(2), taken, fewer)).code is ErrorCode.AMBIGUOUS_TARGET


def test_an_element_in_another_window_of_the_same_package_is_still_found():
    dialog = fixture_screen("dialog-over-app")
    taken = snapshot_of(dialog, ID, DEVICE)
    assert locate(ref(2), taken, dialog).node == consumer_of(dialog, labelled(dialog, "Allow")).id


def store_with(tmp_path, screen, epoch=0, device=DEVICE):
    store = SnapshotStore(tmp_path)
    taken = snapshot_of(screen, ID, device, epoch)
    store.record(taken)
    return store, taken


def test_an_observation_from_this_device_boot_and_epoch_is_accepted(tmp_path):
    store, taken = store_with(tmp_path, buttons("[0,0][100,100]"))
    assert observed_snapshot(ref(1), store, DEVICE, 0) == taken
    assert observed_snapshot(None, store, DEVICE, 0) == taken


def test_a_ref_after_input_was_sent_is_spent_and_a_query_must_observe_first(tmp_path):
    store, _ = store_with(tmp_path, buttons("[0,0][100,100]"), epoch=3)
    spent = refused(lambda: observed_snapshot(ref(1), store, DEVICE, 4))
    assert (spent.code, spent.details) == (ErrorCode.STALE_REF, {"reason": "spent"})
    assert refused(lambda: observed_snapshot(None, store, DEVICE, 4)).code is ErrorCode.OBSERVE_FIRST


def test_a_ref_from_before_a_reboot_is_stale_with_the_reason_rebooted(tmp_path):
    store, _ = store_with(tmp_path, buttons("[0,0][100,100]"))
    rebooted = DeviceIdentity(J7_SERIAL, BootId("another-boot"))
    error = refused(lambda: observed_snapshot(ref(1), store, rebooted, 0))
    assert (error.code, error.details) == (ErrorCode.STALE_REF, {"reason": "rebooted"})


def test_a_ref_used_against_another_device_is_wrong_device_and_names_the_owner(tmp_path):
    store, _ = store_with(tmp_path, buttons("[0,0][100,100]"))
    other = DeviceIdentity(Serial("emulator-5554"), J7_BOOT)
    error = refused(lambda: observed_snapshot(ref(1), store, other, 0))
    assert error.code is ErrorCode.WRONG_DEVICE and error.details == {"ref_device": J7_SERIAL}


def test_a_snapshot_that_was_never_taken_is_not_found_and_no_snapshot_at_all_is_observe_first(tmp_path):
    store = SnapshotStore(tmp_path)
    assert refused(lambda: observed_snapshot(ref(1), store, DEVICE, 0)).code is ErrorCode.SNAPSHOT_NOT_FOUND
    assert refused(lambda: observed_snapshot(None, store, DEVICE, 0)).code is ErrorCode.OBSERVE_FIRST
