"""`Phone` and `PhoneHub` over adb, the u2.jar server and `adb shell`.

The server is started detached (`nohup app_process ... uia2.Main`, A3-3) the first time a
process needs it and left running; the idle stop after 15 minutes belongs to unit 2 and runs
`pkill -f uia2.Main`. The uiautomator2 IME APK is never installed (A3-1).
"""

from __future__ import annotations

from agent_phone.adapters.uiautomator2.adb import Adb, first_line, parse_devices
from agent_phone.adapters.uiautomator2.rpc import JsonRpc
from agent_phone.adapters.uiautomator2.server import Server
from agent_phone.adapters.uiautomator2.shell import Shell
from agent_phone.core.device import Connected, DeviceInfo, DeviceState, Serial
from agent_phone.core.outcome import ErrorCode, Refusal
from agent_phone.core.phone import Delivery, Permit
from agent_phone.core.screen import Screen
from agent_phone.core.wait.clock import Clock, SystemClock


class U2Phone:
    def __init__(self, serial: Serial, rpc: JsonRpc, shell: Shell) -> None:
        self._serial = serial
        self._rpc = rpc
        self._shell = shell

    def info(self) -> DeviceInfo:
        raise NotImplementedError

    def read(self) -> Screen:
        """`dumpWindowHierarchy(false, 50)`, then `parse.parse_hierarchy`. A read may be repeated
        freely; it never touches the screen."""
        raise NotImplementedError

    def state(self) -> DeviceState:
        raise NotImplementedError

    def inject(self, permit: Permit) -> Delivery:
        """Refuse a permit minted for another device identity (NotSent(WRONG_DEVICE)); it can
        only happen through a wiring bug, and the check costs nothing. Then one call:

        Tap/LongPress  -> rpc click(x, y) / click(x, y, ms)
        Activate       -> NotSent(NOT_SUPPORTED): u2.jar exposes no ACTION_CLICK on a node
        Swipe          -> rpc swipe(fx, fy, tx, ty, steps)
        SetText        -> address.pin, then rpc setText(selector, text)
        Key            -> rpc pressKeyCode(code)    BACK 4, HOME 3, RECENTS 187, ENTER 66
        SetPower       -> rpc pressKeyCode(224 wake / 223 sleep)
        SetClipboard   -> rpc setClipboard(label, text)
        Launch, Stop, OpenUri, Rotate -> shell.run
        """
        raise NotImplementedError

    def clipboard(self) -> str:
        raise NotImplementedError

    def screenshot(self) -> bytes:
        raise NotImplementedError


class U2Hub:
    def __init__(self, adb: Adb, idle_limit_s: int = 15 * 60, clock: Clock | None = None) -> None:
        self._adb = adb
        self._idle_limit_s = idle_limit_s
        self._clock = clock or SystemClock()

    def connected(self) -> tuple[Connected, ...]:
        """`adb devices -l`; `unauthorized` and `offline` rows are listed with ready=False."""
        result = self._adb.run(("devices", "-l"))
        if result.status != 0:
            raise Refusal(ErrorCode.TRANSPORT, f"adb devices failed: {first_line(result.stderr)}.")
        return parse_devices(result.stdout)

    def inspect(self, serial: Serial) -> DeviceInfo:
        return Shell(serial, self._adb).facts()

    def server(self, serial: Serial) -> Server:
        return Server(serial, self._adb, self._idle_limit_s, self._clock)

    def open(self, serial: Serial) -> U2Phone:
        """Forward a free host port to the server port, start the server if its health check
        fails, and wait for it within a deadline. Raises `Refusal(SERVER_UNAVAILABLE)`."""
        raise NotImplementedError
