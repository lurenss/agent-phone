"""`Phone` and `PhoneHub` over adb, the u2.jar server and `adb shell`.

The server is started detached (`server.py`, A3-3) the first time a process needs it and left
running. The phone's watchdog stops it after the idle limit, and every client call counts as use
(`U2Phone` touches the last-use file at most once per touch interval). The uiautomator2 IME APK
is never installed (A3-1).
"""

from __future__ import annotations

from agent_phone.adapters.uiautomator2.adb import Adb, first_line, parse_devices
from agent_phone.adapters.uiautomator2.parse import parse_hierarchy
from agent_phone.adapters.uiautomator2.rpc import JsonRpc, Phase
from agent_phone.adapters.uiautomator2.server import Forward, Server, touch_interval, touch_script
from agent_phone.adapters.uiautomator2.shell import Shell
from agent_phone.core.device import Connected, DeviceInfo, DeviceState, Serial
from agent_phone.core.outcome import ErrorCode, Refusal
from agent_phone.core.phone import Delivery, Permit
from agent_phone.core.screen import Screen
from agent_phone.core.wait.clock import Clock, SystemClock

READ_TIMEOUT_S = 15.0
DUMP_METHOD = "dumpWindowHierarchy"
MAX_DEPTH = 50
ALREADY_REGISTERED = "already registered"


class U2Phone:
    def __init__(
        self,
        info: DeviceInfo,
        rpc: JsonRpc,
        forward: Forward,
        server: Server,
        idle_limit_s: int,
        clock: Clock,
    ) -> None:
        self._info = info
        self._rpc = rpc
        self._forward = forward
        self._server = server
        self._clock = clock
        self._touch_every = touch_interval(idle_limit_s)
        self._touched = clock.now()

    def info(self) -> DeviceInfo:
        return self._info

    def read(self) -> Screen:
        """`dumpWindowHierarchy(false, 50)`, then `parse.parse_hierarchy`. A read may be repeated
        freely; it never touches the screen."""
        self._keepalive()
        return parse_hierarchy(self._dump(), self._info.display, self._info.default_ime)

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

    def close(self) -> None:
        self._forward.close()

    def _keepalive(self) -> None:
        if self._clock.now() - self._touched >= self._touch_every:
            self._server.touch()
            self._touched = self._clock.now()

    def _dump(self) -> str:
        serial = self._info.identity.serial
        reply = self._rpc.call(DUMP_METHOD, [False, MAX_DEPTH])
        if reply.phase is not Phase.ANSWERED:
            raise Refusal(
                ErrorCode.SERVER_UNAVAILABLE, f"The server on {serial} did not answer the screen read."
            )
        if reply.error_message is not None:
            if ALREADY_REGISTERED in reply.error_message:
                raise Refusal(
                    ErrorCode.DEVICE_BUSY,
                    f"Another UiAutomation client holds {serial} (A3-4). Wait for it, or stop that tool.",
                )
            raise Refusal(
                ErrorCode.SERVER_UNAVAILABLE,
                f"The server on {serial} failed the screen read: {reply.error_message[:200]}",
            )
        if not isinstance(reply.result, str):
            raise Refusal(ErrorCode.TRANSPORT, f"The screen read on {serial} did not return text.")
        if not reply.result.strip():
            raise Refusal(ErrorCode.NO_SURFACE, "The screen dump is empty. The screen may be off.")
        return reply.result


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
        """Forward a free host port to the server port, read the facts (and count this use),
        and start the server if its health check fails, within a deadline. Raises
        `Refusal(SERVER_UNAVAILABLE)`."""
        forward = Forward.open(self._adb, serial)
        try:
            touch = touch_script(touch_interval(self._idle_limit_s))
            info = Shell(serial, self._adb).facts(also=touch)
            rpc = JsonRpc(forward.port, READ_TIMEOUT_S)
            server = self.server(serial)
            server.ensure(rpc)
            return U2Phone(info, rpc, forward, server, self._idle_limit_s, self._clock)
        except BaseException:
            forward.close()
            raise
