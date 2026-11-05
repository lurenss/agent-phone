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
from agent_phone.core.outcome import ErrorCode, Refusal

Serial = NewType("Serial", str)
BootId = NewType("BootId", str)
Package = NewType("Package", str)


@dataclass(frozen=True, slots=True)
class DeviceIdentity:
    serial: Serial
    boot_id: BootId


class Capability(Enum):
    """What a backend can do beyond `read`. Core plans around these. Without POINT_INPUT, a touch
    at a point (a tap, a long press or a swipe) is refused with NOT_SUPPORTED before a permit is
    spent, and so are the clipboard and screenshot commands without theirs."""

    POINT_INPUT = "point_input"
    SEMANTIC_CLICK = "semantic_click"
    WINDOW_LAYERS = "window_layers"
    NODE_IDS = "node_ids"
    TOASTS = "toasts"
    CLIPBOARD = "clipboard"
    SCREENSHOT = "screenshot"


@dataclass(frozen=True, slots=True)
class DeviceInfo:
    """Facts read from the device once per process. Nothing here is assumed from the J7.

    `default_ime` is the package of the default keyboard, which names the keyboard window in a
    dump. `locale` is the language tag of the user's locale, such as `en-US`.
    """

    identity: DeviceIdentity
    model: str
    api_level: int
    abi: str
    display: Size
    density_dpi: int
    locale: str
    default_ime: Package | None
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


@dataclass(frozen=True, slots=True)
class Listed:
    """One row of `devices`. `info` is None for a device that is not ready, and for a ready one
    whose facts could not be read, in which case `problem` says why."""

    connected: Connected
    info: DeviceInfo | None
    problem: str | None
    profile: str | None


@dataclass(frozen=True, slots=True)
class DeviceList:
    devices: tuple[Listed, ...]


def select_device(
    connected: Sequence[Connected], requested: Serial | None, ref_device: Serial | None
) -> Serial:
    """Pick the device for this command, or raise `Refusal` (NO_DEVICE, DEVICE_AMBIGUOUS, WRONG_DEVICE).

    A ref names its own device through its snapshot record, so `click @id:eN` needs no `-d`.
    """
    if requested is not None and ref_device is not None and requested != ref_device:
        raise Refusal(
            ErrorCode.WRONG_DEVICE,
            f"-d {requested} contradicts the ref, which belongs to {ref_device}.",
            {"requested": requested, "ref_device": ref_device},
        )
    want = requested or ref_device
    if want is not None:
        found = next((device for device in connected if device.serial == want), None)
        if found is None:
            raise Refusal(
                ErrorCode.NO_DEVICE,
                f"No device {want} is connected. {listing(connected)}",
                {"serial": want, "connected": [device.serial for device in connected]},
            )
        if not found.ready:
            raise Refusal(
                ErrorCode.NO_DEVICE,
                f"Device {want} is connected but adb does not list it as ready. "
                "It may be unauthorized or offline.",
                {"serial": want},
            )
        return found.serial
    ready = [device for device in connected if device.ready]
    if not ready:
        raise Refusal(
            ErrorCode.NO_DEVICE,
            f"No device is connected and ready. {listing(connected)}",
            {"connected": [device.serial for device in connected]},
        )
    if len(ready) > 1:
        raise Refusal(
            ErrorCode.DEVICE_AMBIGUOUS,
            f"Several devices are ready: {', '.join(describe(device) for device in ready)}. "
            "Pass -d <serial> to pick one.",
            {"devices": [device.serial for device in ready]},
        )
    return ready[0].serial


def describe(device: Connected) -> str:
    return f"{device.serial} ({device.model})" if device.model else device.serial


def listing(connected: Sequence[Connected]) -> str:
    if not connected:
        return "adb lists no device."
    return (
        "adb lists "
        + ", ".join(describe(device) + ("" if device.ready else " (not ready)") for device in connected)
        + "."
    )
