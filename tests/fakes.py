"""Fakes behind the `PhoneHub` and `Phone` protocols, so selection, locking and the envelope are
tested with no device."""

from __future__ import annotations

import io
import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from support import FakeClock

from agent_phone.cli.process import run
from agent_phone.cli.settings import Settings
from agent_phone.core.device import BootId, Connected, DeviceIdentity, DeviceInfo, Package, Serial
from agent_phone.core.geometry import Size
from agent_phone.core.outcome import ErrorCode, Refusal
from agent_phone.core.phone import ServerStatus
from agent_phone.core.screen import Screen
from agent_phone.core.wait.clock import Clock

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


class FakeServer:
    def __init__(self) -> None:
        self.running = False
        self.calls: list[str] = []

    def status(self) -> ServerStatus:
        return ServerStatus(
            self.running, self.running, 900 if self.running else None, 3 if self.running else None
        )

    def start(self) -> ServerStatus:
        self.calls.append("start")
        self.running = True
        return self.status()

    def stop(self) -> ServerStatus:
        self.calls.append("stop")
        self.running = False
        return self.status()


class FakePhone:
    """A device that shows the screens it is given, one per read, the last one forever. A screen
    that is a Refusal is raised instead, like a backend that cannot read."""

    def __init__(self, info: DeviceInfo, *screens: Screen | Refusal) -> None:
        self._info = info
        self._screens = screens
        self.reads = 0
        self.closed = False

    def info(self) -> DeviceInfo:
        return self._info

    def read(self) -> Screen:
        shown = self._screens[min(self.reads, len(self._screens) - 1)]
        self.reads += 1
        if isinstance(shown, Refusal):
            raise shown
        return shown

    def close(self) -> None:
        self.closed = True

    def state(self) -> object:
        raise AssertionError("unit 2 asks for no device state")

    def inject(self, permit: object) -> object:
        raise AssertionError("unit 2 sends no input")

    def clipboard(self) -> str:
        raise AssertionError("unit 2 reads no clipboard")

    def screenshot(self) -> bytes:
        raise AssertionError("unit 2 takes no screenshot")


class FakeHub:
    def __init__(
        self,
        connected: Sequence[Connected],
        infos: Mapping[Serial, DeviceInfo] | None = None,
        problems: Mapping[Serial, str] | None = None,
        screens: Sequence[Screen | Refusal] = (),
        open_problem: Refusal | None = None,
    ) -> None:
        self._connected = tuple(connected)
        self._infos = dict(infos or {d.serial: info_for(d.serial) for d in connected if d.ready})
        self._problems = dict(problems or {})
        self.inspected: list[Serial] = []
        self.servers: dict[Serial, FakeServer] = {}
        self.phones: list[FakePhone] = []
        self.first_read_asked: list[bool] = []
        self._screens = tuple(screens)
        self._open_problem = open_problem

    def connected(self) -> tuple[Connected, ...]:
        return self._connected

    def inspect(self, serial: Serial) -> DeviceInfo:
        self.inspected.append(serial)
        if serial in self._problems:
            raise Refusal(ErrorCode.TRANSPORT, self._problems[serial])
        return self._infos[serial]

    def server(self, serial: Serial) -> FakeServer:
        return self.servers.setdefault(serial, FakeServer())

    def open(self, serial: Serial, first_read: bool = False) -> FakePhone:
        self.first_read_asked.append(first_read)
        if self._open_problem is not None:
            raise self._open_problem
        phone = FakePhone(self._infos[serial], *self._screens)
        self.phones.append(phone)
        return phone


def invoke(argv, hub, root=None, lock_wait_s=0.0, clock: Clock | None = None):
    """Run one command line against `hub` and return its exit code and its one envelope."""
    out = io.StringIO()
    settings = Settings(state_root=root or Path("/nonexistent-agent-phone-root"), lock_wait_s=lock_wait_s)
    code = run(argv, hub, settings, out, clock or FakeClock())
    lines = out.getvalue().splitlines()
    assert len(lines) == 1, "one command prints one envelope"
    return code, json.loads(lines[0])
