"""Fakes behind the `PhoneHub` and `Phone` protocols, so selection, locking and the envelope are
tested with no device."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from agent_phone.core.device import BootId, Connected, DeviceIdentity, DeviceInfo, Package, Serial
from agent_phone.core.geometry import Size
from agent_phone.core.outcome import ErrorCode, Refusal

J7_SERIAL = Serial("0a1b2c3d4e5f6a7b")
J7_BOOT = BootId("8d3f6c1e-0b5a-4c2e-9f1d-2a7b3c4d5e6f")
EMULATOR_SERIAL = Serial("emulator-5554")


def info_for(serial: Serial, model: str = "SM-J730F", boot: BootId = J7_BOOT) -> DeviceInfo:
    return DeviceInfo(
        DeviceIdentity(serial, boot),
        model,
        28,
        "armeabi-v7a",
        Size(1080, 1920),
        420,
        "en-US",
        Package("com.sec.android.inputmethod"),
        frozenset(),
    )


class FakeHub:
    def __init__(
        self,
        connected: Sequence[Connected],
        infos: Mapping[Serial, DeviceInfo] | None = None,
        problems: Mapping[Serial, str] | None = None,
    ) -> None:
        self._connected = tuple(connected)
        self._infos = dict(infos or {d.serial: info_for(d.serial) for d in connected if d.ready})
        self._problems = dict(problems or {})
        self.inspected: list[Serial] = []

    def connected(self) -> tuple[Connected, ...]:
        return self._connected

    def inspect(self, serial: Serial) -> DeviceInfo:
        self.inspected.append(serial)
        if serial in self._problems:
            raise Refusal(ErrorCode.TRANSPORT, self._problems[serial])
        return self._infos[serial]
