"""The ledger makes the retry rule structural: every input spends every older ref of its device,
and only a proven non-send gives the spend back."""

import json

import pytest
from fakes import J7_BOOT, J7_SERIAL
from support import fixture_screen, snapshot_of

from agent_phone.core.act.ledger import Ledger, unrefunded
from agent_phone.core.device import BootId, DeviceIdentity
from agent_phone.core.outcome import ErrorCode, Refusal
from agent_phone.core.phone import Key, KeyName
from agent_phone.core.policy.engine import Clear, ClearReason, Grant
from agent_phone.core.refs.resolve import RefTarget, observed_snapshot
from agent_phone.core.refs.store import SnapshotStore
from agent_phone.core.snapshot.snapshot import RefToken, SnapshotId

DEVICE = DeviceIdentity(J7_SERIAL, J7_BOOT)
BACK = Key(KeyName.BACK)
CLEAR = Clear(ClearReason.NOT_LABELED_INPUT)


def on_disk(root):
    return json.loads((root / "devices" / J7_SERIAL / "ledger.json").read_text())


def test_a_spend_is_on_disk_before_the_permit_exists_and_names_the_new_epoch(tmp_path):
    ledger = Ledger(tmp_path, DEVICE)
    permit = ledger.spend(BACK, CLEAR, Grant.none())
    assert on_disk(tmp_path) == {"boot_id": J7_BOOT, "epoch": 1}
    assert (permit.epoch, permit.device, permit.action, permit.verdict) == (1, DEVICE, BACK, CLEAR)
    assert ledger.spend(BACK, CLEAR, Grant.none()).epoch == 2
    assert Ledger(tmp_path, DEVICE).epoch() == 2


def test_every_input_spends_every_older_ref_of_its_device(tmp_path):
    store = SnapshotStore(tmp_path)
    taken = snapshot_of(fixture_screen("settings-home"), SnapshotId("k3x9q"), DEVICE, epoch=0)
    store.record(taken)
    ledger = Ledger(tmp_path, DEVICE)
    target = RefTarget(RefToken(taken.id, 7))
    assert observed_snapshot(target, store, DEVICE, ledger.epoch()) == taken
    ledger.spend(BACK, CLEAR, Grant.none())
    with pytest.raises(Refusal) as refused:
        observed_snapshot(target, store, DEVICE, ledger.epoch())
    assert (refused.value.code, refused.value.details) == (ErrorCode.STALE_REF, {"reason": "spent"})
    with pytest.raises(Refusal) as refused:
        observed_snapshot(None, store, DEVICE, ledger.epoch())
    assert refused.value.code is ErrorCode.OBSERVE_FIRST


def test_a_refund_gives_back_exactly_the_newest_spend_and_only_once(tmp_path):
    ledger = Ledger(tmp_path, DEVICE)
    first = ledger.spend(BACK, CLEAR, Grant.none())
    second = ledger.spend(BACK, CLEAR, Grant.none())
    with pytest.raises(Refusal) as refused:
        ledger.refund(first)
    assert refused.value.code is ErrorCode.INTERNAL and ledger.epoch() == 2
    ledger.refund(second)
    assert ledger.epoch() == 1
    with pytest.raises(Refusal):
        ledger.refund(second)
    assert ledger.epoch() == 1


def test_the_process_knows_whether_it_spent_a_permit_it_did_not_refund(tmp_path):
    ledger = Ledger(tmp_path, DEVICE)
    assert not unrefunded()
    permit = ledger.spend(BACK, CLEAR, Grant.none())
    assert unrefunded()
    ledger.refund(permit)
    assert not unrefunded()
    ledger.spend(BACK, CLEAR, Grant.none())
    assert unrefunded()


def test_a_spend_after_a_reboot_starts_the_new_boot_at_one(tmp_path):
    Ledger(tmp_path, DEVICE).spend(BACK, CLEAR, Grant.none())
    Ledger(tmp_path, DEVICE).spend(BACK, CLEAR, Grant.none())
    rebooted = DeviceIdentity(J7_SERIAL, BootId("a-later-boot"))
    assert Ledger(tmp_path, rebooted).epoch() == 0
    assert Ledger(tmp_path, rebooted).spend(BACK, CLEAR, Grant.none()).epoch == 1
    assert on_disk(tmp_path) == {"boot_id": "a-later-boot", "epoch": 1}
