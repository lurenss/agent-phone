import subprocess
import sys

import pytest
from support import FakeClock

from agent_phone.core.device import Serial
from agent_phone.core.outcome import ErrorCode, Refusal
from agent_phone.core.refs.store import SnapshotStore
from agent_phone.core.wait.clock import POLL_GAP_S, SystemClock

J7 = Serial("0a1b2c3d4e5f6a7b")
EMULATOR = Serial("emulator-5554")

HOLDER = """
import sys
from pathlib import Path

from agent_phone.core.device import Serial
from agent_phone.core.refs.store import SnapshotStore
from agent_phone.core.wait.clock import POLL_GAP_S, SystemClock

with SnapshotStore(Path(sys.argv[1])).lock(Serial(sys.argv[2]), SystemClock(), 5, "snapshot"):
    print("held", flush=True)
    sys.stdin.read()
"""


def busy(store, serial, wait_s, clock=None) -> Refusal:
    with pytest.raises(Refusal) as raised, store.lock(serial, clock or FakeClock(), wait_s):
        pass
    assert raised.value.code is ErrorCode.DEVICE_BUSY
    return raised.value


def test_a_second_holder_on_the_same_device_is_refused_after_its_wait(tmp_path):
    store = SnapshotStore(tmp_path)
    clock = FakeClock()
    with store.lock(J7, clock, 5, "snapshot"):
        error = busy(store, J7, 3, clock)
    assert 3 <= clock.time <= 3 + POLL_GAP_S, "the wait is bounded by the budget it was given"
    assert str(J7) in error.message and "3 s" in error.message


def test_the_lock_is_free_again_after_the_holder_leaves(tmp_path):
    store = SnapshotStore(tmp_path)
    with store.lock(J7, FakeClock(), 0):
        pass
    with store.lock(J7, FakeClock(), 0):
        pass


def test_a_holder_that_fails_still_lets_go(tmp_path):
    store = SnapshotStore(tmp_path)
    with pytest.raises(RuntimeError), store.lock(J7, FakeClock(), 0):
        raise RuntimeError
    with store.lock(J7, FakeClock(), 0):
        pass


def test_two_devices_never_wait_for_each_other(tmp_path):
    store = SnapshotStore(tmp_path)
    with store.lock(J7, FakeClock(), 0), store.lock(EMULATOR, FakeClock(), 0):
        pass


def test_another_process_holds_the_lock_and_the_refusal_names_it(tmp_path):
    holder = subprocess.Popen(
        [sys.executable, "-c", HOLDER, str(tmp_path), J7],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert holder.stdout.readline().strip() == "held"
        error = busy(SnapshotStore(tmp_path), J7, 0.2, SystemClock())
        assert f"pid {holder.pid} snapshot" in error.message
    finally:
        holder.communicate("")
    with SnapshotStore(tmp_path).lock(J7, SystemClock(), 0):
        pass
