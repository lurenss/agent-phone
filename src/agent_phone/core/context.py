"""What a command runs against: one device, its ledger, the store, the merged policy, a clock.

Built once per process by the CLI (`cli/driver.py`), the only place a backend meets core, and
only after the device lock is held. Commands receive it; nothing in core constructs one.
"""

from __future__ import annotations

from dataclasses import dataclass

from agent_phone.core.act.ledger import Ledger
from agent_phone.core.device import DeviceInfo, DeviceProfile
from agent_phone.core.phone import Phone
from agent_phone.core.policy.rules import Policy
from agent_phone.core.refs.store import SnapshotStore
from agent_phone.core.wait.clock import Clock


@dataclass(frozen=True, slots=True)
class Context:
    phone: Phone
    info: DeviceInfo
    profile: DeviceProfile | None
    policy: Policy
    store: SnapshotStore
    ledger: Ledger
    clock: Clock
