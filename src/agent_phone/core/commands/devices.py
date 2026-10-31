"""`agent-phone devices`. Lists every device adb knows, with the facts read from each ready one
and the profile that applies. Runs without a Context: it needs no lock and drives nothing."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from agent_phone.core.device import Connected, DeviceList, DeviceProfile, Listed
from agent_phone.core.outcome import Outcome, Read, Refusal, Refused
from agent_phone.core.phone import PhoneHub


@dataclass(frozen=True, slots=True)
class DevicesCommand:
    pass


def run(hub: PhoneHub, profiles: Sequence[DeviceProfile]) -> Outcome:
    try:
        connected = hub.connected()
    except Refusal as refusal:
        return Refused.of(refusal)
    return Read(DeviceList(tuple(list_one(hub, device, profiles) for device in connected)))


def list_one(hub: PhoneHub, device: Connected, profiles: Sequence[DeviceProfile]) -> Listed:
    """One device's facts failing is that row's `problem`, so one bad phone never hides the rest."""
    profile = next((p.name for p in profiles if p.serial == device.serial), None)
    if not device.ready:
        return Listed(device, None, None, profile)
    try:
        return Listed(device, hub.inspect(device.serial), None, profile)
    except Refusal as refusal:
        return Listed(device, None, refusal.message, profile)
