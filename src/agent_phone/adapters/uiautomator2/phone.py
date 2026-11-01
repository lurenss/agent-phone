"""`Phone` and `PhoneHub` over adb, the u2.jar server and `adb shell`.

The server is started detached (`server.py`, A3-3) the first time a process needs it and left
running. The phone's watchdog stops it after the idle limit, and every client call counts as use
(`U2Phone` touches the last-use file at most once per touch interval). The uiautomator2 IME APK
is never installed (A3-1).
"""

from __future__ import annotations

import base64
from dataclasses import replace

from agent_phone.adapters.uiautomator2.adb import Adb, first_line, parse_devices
from agent_phone.adapters.uiautomator2.address import pin
from agent_phone.adapters.uiautomator2.delivery import classify
from agent_phone.adapters.uiautomator2.first_read import MAX_AGE_S, FirstRead, overlap
from agent_phone.adapters.uiautomator2.parse import parse_hierarchy
from agent_phone.adapters.uiautomator2.rpc import JsonRpc, Phase
from agent_phone.adapters.uiautomator2.server import Forward, Server, touch_interval, touch_script
from agent_phone.adapters.uiautomator2.shell import Shell
from agent_phone.core.device import Capability, Connected, DeviceInfo, DeviceState, Power, Serial
from agent_phone.core.outcome import ErrorCode, Refusal
from agent_phone.core.phone import (
    Activate,
    Delivery,
    Key,
    KeyName,
    Launch,
    LongPress,
    NotSent,
    OpenUri,
    Permit,
    Rotate,
    SetClipboard,
    SetPower,
    SetText,
    Stop,
    Swipe,
    Tap,
)
from agent_phone.core.screen import Screen
from agent_phone.core.wait.clock import Clock, SystemClock

READ_TIMEOUT_S = 15.0
SCREENSHOT_QUALITY = 90
STEP_MS = 5
"""UiDevice.swipe moves one step about every 5 ms."""
KEY_CODES = {KeyName.BACK: 4, KeyName.HOME: 3, KeyName.RECENTS: 187, KeyName.ENTER: 66}
CAPABILITIES = frozenset({Capability.CLIPBOARD, Capability.SCREENSHOT})
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
        shell: Shell,
        first: FirstRead | None = None,
    ) -> None:
        self._info = replace(info, capabilities=CAPABILITIES)
        self._rpc = rpc
        self._shell = shell
        self._forward = forward
        self._server = server
        self._clock = clock
        self._touch_every = touch_interval(idle_limit_s)
        self._touched = clock.now()
        self._first = first

    def info(self) -> DeviceInfo:
        return self._info

    def read(self) -> Screen:
        """`dumpWindowHierarchy(false, 50)`, then `parse.parse_hierarchy`. A read may be repeated
        freely; it never touches the screen. The first read of a phone opened with a `FirstRead`
        uses it when it is young enough, and every later read asks the server."""
        self._keepalive()
        return parse_hierarchy(self._dump(), self._info.display, self._info.default_ime)

    def state(self) -> DeviceState:
        raise NotImplementedError("no command reads the power or lock state yet")

    def inject(self, permit: Permit) -> Delivery:
        """Refuse a permit minted for another device identity (NotSent(WRONG_DEVICE)); it can
        only happen through a wiring bug, and the check costs nothing. Then one call, never
        retried (A2-6). The jar has no semantic click (A2-11), so `Activate` is NOT_SUPPORTED."""
        if permit.device != self._info.identity:
            return NotSent(ErrorCode.WRONG_DEVICE, f"The permit was made for {permit.device.serial}.")
        self._keepalive()
        match permit.action:
            case Tap(point=p):
                return classify(self._rpc.call("click", [p.x, p.y]))
            case LongPress(point=p, duration_ms=ms):
                return classify(self._rpc.call("click", [p.x, p.y, ms]))
            case Activate():
                return NotSent(ErrorCode.NOT_SUPPORTED, "This backend cannot click a node without a point.")
            case Swipe(start=a, end=b, duration_ms=ms):
                steps = max(2, ms // STEP_MS)
                return classify(self._rpc.call("swipe", [a.x, a.y, b.x, b.y, steps]))
            case SetText(field=field, text=text):
                selector = pin(self._rpc, field)
                if isinstance(selector, NotSent):
                    return selector
                return classify(self._rpc.call("setText", [selector, text]))
            case Key(key=key):
                return classify(self._rpc.call("pressKeyCode", [KEY_CODES[key]]))
            case SetPower(power=power):
                return classify(self._rpc.call("pressKeyCode", [224 if power is Power.ON else 223]))
            case SetClipboard(text=text):
                return classify(self._rpc.call("setClipboard", [None, text]))
            case Launch() | Stop() | OpenUri() | Rotate() as action:
                return self._shell.run(action)

    def clipboard(self) -> str | None:
        self._keepalive()
        reply = self._rpc.call("getClipboard", [])
        if reply.phase is not Phase.ANSWERED or reply.error_message is not None:
            raise Refusal(ErrorCode.SERVER_UNAVAILABLE, "The server did not read the clipboard.")
        return reply.result if isinstance(reply.result, str) else None

    def screenshot(self) -> bytes:
        """A JPEG through UiAutomation, at full size."""
        self._keepalive()
        reply = self._rpc.call("takeScreenshot", [1.0, SCREENSHOT_QUALITY])
        if reply.phase is not Phase.ANSWERED or not isinstance(reply.result, str):
            raise Refusal(ErrorCode.SERVER_UNAVAILABLE, "The server did not take the screenshot.")
        return base64.b64decode(reply.result)

    def close(self) -> None:
        self._forward.close()

    def _keepalive(self) -> None:
        if self._clock.now() - self._touched >= self._touch_every:
            self._server.touch()
            self._touched = self._clock.now()

    def _dump(self) -> str:
        first, self._first = self._first, None
        if first is not None and self._clock.now() - first.taken_at <= MAX_AGE_S:
            return first.text()
        return dump_text(self._rpc, self._info.identity.serial)


def dump_text(rpc: JsonRpc, serial: Serial) -> str:
    """The server's dump of every window, or the `Refusal` that says what went wrong."""
    reply = rpc.call(DUMP_METHOD, [False, MAX_DEPTH])
    if reply.phase is not Phase.ANSWERED:
        raise Refusal(ErrorCode.SERVER_UNAVAILABLE, f"The server on {serial} did not answer the screen read.")
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
    def __init__(
        self,
        adb: Adb,
        idle_limit_s: int = 15 * 60,
        clock: Clock | None = None,
        overlap_first_read: bool = True,
    ) -> None:
        self._adb = adb
        self._idle_limit_s = idle_limit_s
        self._clock = clock or SystemClock()
        self._overlap = overlap_first_read

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

    def open(self, serial: Serial, first_read: bool = False) -> U2Phone:
        """Forward a free host port to the server port, read the facts (and count this use),
        and start the server if its health check fails, within a deadline. Raises
        `Refusal(SERVER_UNAVAILABLE)`.

        With `first_read`, the first screen read happens while the facts are read, which a
        command that reads once asks for (`first_read.py`)."""
        forward = Forward.open(self._adb, serial)
        try:
            touch = touch_script(touch_interval(self._idle_limit_s))
            shell = Shell(serial, self._adb)
            rpc = JsonRpc(forward.port, READ_TIMEOUT_S)
            server = self.server(serial)
            first = None
            if first_read and self._overlap:
                info, first = overlap(
                    lambda: shell.facts(also=touch),
                    lambda: server.ensure(rpc),
                    lambda: dump_text(rpc, serial),
                    self._clock,
                )
            else:
                info = shell.facts(also=touch)
                server.ensure(rpc)
            return U2Phone(info, rpc, forward, server, self._idle_limit_s, self._clock, shell, first)
        except BaseException:
            forward.close()
            raise
