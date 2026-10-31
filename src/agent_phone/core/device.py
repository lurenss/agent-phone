"""Which device a command talks to, what it is, and what its owner forbids on it.

A device is one boot of one phone. The serial names the phone (an emulator serial such as
`emulator-5554` names a port, and a different AVD can take it later), and the boot id names the
boot. Every snapshot records the `DeviceIdentity` it was read from, so a ref used against
another phone, another AVD on the same port, or the same phone after a reboot fails closed.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from typing import NewType

from agent_phone.core.geometry import Size

Serial = NewType("Serial", str)
BootId = NewType("BootId", str)
Package = NewType("Package", str)


@dataclass(frozen=True, slots=True)
class DeviceIdentity:
    serial: Serial
    boot_id: BootId


class Capability(Enum):
    """What a backend can do beyond `read` and coordinate input. Core plans around these."""

    SEMANTIC_CLICK = "semantic_click"
    WINDOW_LAYERS = "window_layers"
    NODE_IDS = "node_ids"
    TOASTS = "toasts"
    CLIPBOARD = "clipboard"
    SCREENSHOT = "screenshot"


@dataclass(frozen=True, slots=True)
class DeviceInfo:
    """Facts read from the device once per process. Nothing here is assumed from the J7."""

    identity: DeviceIdentity
    model: str
    api_level: int
    abi: str
    display: Size
    density_dpi: int
    locale: str
    capabilities: frozenset[Capability]


class Power(Enum):
    ON = "on"
    OFF = "off"


class Lock(Enum):
    UNLOCKED = "unlocked"
    LOCKED = "locked"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class DeviceState:
    """Live device-level state that a screen dump does not show."""

    power: Power
    lock: Lock
    foreground: Package | None


@dataclass(frozen=True, slots=True)
class ProtectedPackage:
    """A package the owner never lets agent-phone stop, disable, clear or uninstall.

    `labels` are the names Settings shows for it, so a "Force stop" tap on its App info page is
    refused too, not only the `stop` command.
    """

    package: Package
    labels: tuple[str, ...]
    reason: str


@dataclass(frozen=True, slots=True)
class DeviceProfile:
    """Owner data for one phone, parsed from a profile file at the CLI boundary.

    Its protections compile into policy deny rules (`agent_phone.core.policy.rules.protect_rules`),
    so the engine is the only place that enforces them. Policy tables written inside the
    profile file itself parse as profile rules, which no consumer policy can disable.
    """

    serial: Serial
    name: str
    protected: tuple[ProtectedPackage, ...]
    policy_files: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Connected:
    serial: Serial
    model: str
    ready: bool


def select_device(
    connected: Sequence[Connected], requested: Serial | None, ref_device: Serial | None
) -> Serial:
    """Pick the device for this command, or raise `Refusal` (NO_DEVICE, DEVICE_AMBIGUOUS, WRONG_DEVICE).

    A ref names its own device through its snapshot record, so `click @id:eN` needs no `-d`.
    """
    # TODO:
    #   if requested and ref_device and requested != ref_device: WRONG_DEVICE
    #   want = requested or ref_device
    #   if want: must be in connected and ready, else NO_DEVICE
    #   else: exactly one ready device, else NO_DEVICE (zero) or DEVICE_AMBIGUOUS (several)
    raise NotImplementedError
