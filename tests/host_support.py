"""The phone host's scripts, run the way the host runs them, against an adb server that is a fake.

`host/phone_host.py` and `host/phone_manifest.py` are not part of the package: each is one file
that runs where agent-phone is not installed. So the tests load a script by path, and run it as a
process with the interpreter flags of its first line."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import ModuleType

SCRIPT = Path(__file__).resolve().parents[1] / "host" / "phone_host.py"
MANIFEST_SCRIPT = SCRIPT.with_name("phone_manifest.py")
J7_ROW = (
    "0a1b2c3d4e5f6a7b       device usb:1-1.2 product:j7y17ltexx model:SM_J730F device:j7y17lte transport_id:1"
)
EMULATOR_ROW = (
    "emulator-5554          device product:sdk_gphone64_arm64 model:sdk_gphone64_arm64 transport_id:2"
)
J7_FACTS = """1
9
Current Battery Service state:
  AC powered: false
  USB powered: true
  Wireless powered: false
  Max charging current: 0
  Max charging voltage: 0
  Charge counter: 3600000
  status: 5
  health: 2
  present: true
  level: 100
  scale: 100
  voltage: 4212
  temperature: 262
  technology: Li-ion
  batterySWSelfDischarging: false
  batteryMiscEvent: 0
  batteryCurrentEvent: 0
  mSecPlugTypeSummary: 2
  LED Charging: true
  LED Low Battery: true
  current now: -76
  charge counter: 3600000
  Adaptive Fast Charging Settings: true
USE_FAKE_BATTERY: false
SEC_FEATURE_BATTERY_SIMULATION: false
FEATURE_WIRELESS_FAST_CHARGER_CONTROL: true
  mWasUsedWirelessFastChargerPreviously: false
  mWirelessFastChargingSettingsEnable: true
LLB CAL: 20180202
LLB MAN:\x20
LLB CURRENT: YEAR2026M10D11
LLB DIFF: 453
FEATURE_HICCUP_CONTROL: false
FEATURE_SUPPORTED_DAILY_BOARD: false
SEC_FEATURE_USE_WIRELESS_POWER_SHARING: false
BatteryInfoBackUp
  mSavedBatteryAsoc: -1
  mSavedBatteryMaxTemp: 467
  mSavedBatteryMaxCurrent: 1632
  mSavedBatteryUsage: 25921
  FEATURE_SAVE_BATTERY_CYCLE: true
  SEC_FEATURE_PREVENT_SWELLING: false
"""
"""What the J7 printed for the one shell line of `phone_manifest.py`, byte for byte (R2-18, R2-19)."""
BOOT = "boot-of-the-tests"
AS_SSHD_WITH_A_CLOCK = f"""
import importlib.util, os, sys, time
spec = importlib.util.spec_from_file_location("phone_host", sys.argv[1])
host = importlib.util.module_from_spec(spec)
spec.loader.exec_module(host)
sys.exit(host.main(sys.argv[2:], dict(os.environ), clock=time.monotonic, boot=lambda: {BOOT!r}))
"""
"""The script reads its clock and its boot id from Linux. A test gives it both, so it runs the
same on any computer."""


def load_script(path: Path = SCRIPT) -> ModuleType:
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def counted(text: str) -> bytes:
    return b"%04x" % len(text) + text.encode()


class FakeAdbServer:
    """Speaks the part of adb's socket protocol the scripts use, as the real server answered it
    in `probes/remote/FINDINGS.md` (R2-6 to R2-21), and records every request. A test that clears
    `forwards` and sets `next_port` back plays an adb server that started again. `bound` keeps each
    port with the phone it was opened for, also one that was closed or moved a moment later."""

    def __init__(self, *rows: str, version: int = 41, first_port: int = 41001) -> None:
        self.rows = list(rows)
        self.version = version
        self.shells: dict[str, str | None] = {}
        self.requests: list[str] = []
        self.forwards: dict[int, tuple[str, int]] = {}
        self.bound: list[tuple[int, str]] = []
        self.taken: set[int] = set()
        self.next_port = first_port
        self._silent: list[socket.socket] = []
        self._sock = socket.create_server(("127.0.0.1", 0))
        self.port = self._sock.getsockname()[1]
        threading.Thread(target=self._serve, daemon=True).start()

    def close(self) -> None:
        self._sock.close()

    def _serve(self) -> None:
        while True:
            try:
                connection, _ = self._sock.accept()
            except OSError:
                return
            with connection:
                request = self._request(connection)
                if request.startswith("host:transport:"):
                    self._shell(connection, request.removeprefix("host:transport:"))
                else:
                    connection.sendall(self._answer(request))

    def _request(self, connection: socket.socket) -> str:
        request = connection.recv(int(connection.recv(4), 16)).decode()
        self.requests.append(request)
        return request

    def _shell(self, connection: socket.socket, serial: str) -> None:
        """The second request of a connection is a service of the phone that the first one named
        (R2-18). The output has no length, so only the close ends it. A connection that must stay
        silent is kept open in `_silent`, as a shell that hangs keeps it (R2-21)."""
        if serial not in self.shells:
            connection.sendall(b"FAIL" + counted(f"device '{serial}' not found"))
            return
        connection.sendall(b"OKAY")
        self._request(connection)
        connection.sendall(b"OKAY")
        said = self.shells[serial]
        if said is None:
            self._silent.append(connection.dup())
        else:
            connection.sendall(said.encode())

    def _answer(self, request: str) -> bytes:
        if request == "host:version":
            return b"OKAY" + counted(f"{self.version:04x}")
        if request == "host:devices-l":
            return b"OKAY" + counted("".join(row + "\n" for row in self.rows))
        if request == "host:list-forward":
            rows = (f"{serial} tcp:{port} tcp:{device}\n" for port, (serial, device) in self.forwards.items())
            return b"OKAY" + counted("".join(rows))
        _, serial, verb, ports = request.split(":", 3)
        if not any(row.split()[0] == serial for row in self.rows):
            return b"FAIL0000"
        if verb == "killforward":
            port = int(ports.removeprefix("tcp:"))
            if self.forwards.pop(port, None) is None:
                return b"FAIL" + counted(f"listener 'tcp:{port}' not found")
            return b"OKAYOKAY"
        named = ports.removeprefix("norebind:")
        host, device = (int(part.removeprefix("tcp:")) for part in named.split(";"))
        if host in self.forwards:
            if named != ports:
                return b"FAIL" + counted("cannot rebind existing socket")
            self.forwards[host] = (serial, device)
            self.bound.append((host, serial))
            return b"OKAYOKAY"
        if host in self.taken:
            return b"FAIL" + counted("cannot bind listener: Address already in use")
        picked = host or self.next_port
        self.next_port += 0 if host else 1
        self.forwards[picked] = (serial, device)
        self.bound.append((picked, serial))
        return b"OKAYOKAY" + counted(str(picked))


def host_command(who: str, *argv: str, as_installed: bool = False) -> list[str]:
    """`as_installed` runs the file itself, with the clock and the boot id of this computer."""
    script = [str(SCRIPT)] if as_installed else ["-c", AS_SSHD_WITH_A_CLOCK, str(SCRIPT)]
    return [sys.executable, "-IS", *script, "--who", who, *argv]


def host_env(state: Path, adb_port: int, request: str | None) -> dict[str, str]:
    env = {
        "PATH": os.environ["PATH"],
        "HOME": str(state),
        "XDG_STATE_HOME": str(state),
        "ANDROID_ADB_SERVER_PORT": str(adb_port),
    }
    return env if request is None else env | {"SSH_ORIGINAL_COMMAND": request}


def call_host(
    script: ModuleType,
    state: Path,
    adb_port: int,
    who: str,
    request: str | None,
    *,
    now: float | None = None,
    boot: str = BOOT,
) -> tuple[int, str]:
    """The script's `main` in this process, at the time and in the boot a test names."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        status = script.main(
            ["--who", who],
            host_env(state, adb_port, request),
            clock=time.monotonic if now is None else lambda: now,
            boot=lambda: boot,
        )
    return status, out.getvalue()


def run_host(
    state: Path, adb_port: int, who: str, request: str | None, *argv: str, as_installed: bool = False
) -> tuple[int, dict[str, object] | str]:
    done = subprocess.run(
        host_command(who, *argv, as_installed=as_installed),
        env=host_env(state, adb_port, request),
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert done.stderr == "", done.stderr
    try:
        return done.returncode, json.loads(done.stdout)
    except ValueError:
        return done.returncode, done.stdout
