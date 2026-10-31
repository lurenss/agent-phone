"""`agent-phone devices`. Lists every connected device with the facts read from it and the
profile that applies. Runs without a Context: it needs no lock and drives nothing."""

from __future__ import annotations

from collections.abc import Sequence

from agent_phone.core.device import DeviceInfo, DeviceProfile
from agent_phone.core.outcome import Outcome


def run(infos: Sequence[DeviceInfo], profiles: Sequence[DeviceProfile]) -> Outcome:
    raise NotImplementedError
