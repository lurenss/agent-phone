"""Device facts and device-level operations that go through `adb shell`, not the server.

Facts come from one shell round trip (A1-1: ~36 ms) per process:

    getprop ro.build.version.sdk; getprop ro.product.cpu.abi; getprop ro.product.model;
    getprop persist.sys.locale; cat /proc/sys/kernel/random/boot_id; wm size; wm density;
    settings get secure default_input_method

`wm size` gives an override line when one is set; the override wins. Output lines are matched
by prefix, and a fact that does not parse is a Refusal(TRANSPORT) naming it, never a default.
"""

from __future__ import annotations

from agent_phone.core.device import DeviceInfo, DeviceState, Package, Serial
from agent_phone.core.phone import Delivery, Launch, OpenUri, Rotate, Stop


class Shell:
    def __init__(self, serial: Serial) -> None:
        self._serial = serial

    def facts(self) -> tuple[DeviceInfo, Package | None]:
        """The DeviceInfo and the default IME package (for window kinds in `parse.py`)."""
        raise NotImplementedError

    def state(self) -> DeviceState:
        """`dumpsys power` for power, `dumpsys window` for keyguard; Lock.UNKNOWN when the
        format of this Android version is not recognised."""
        raise NotImplementedError

    def run(self, action: Launch | Stop | OpenUri | Rotate) -> Delivery:
        # TODO:
        #   Launch  -> monkey -p <pkg> -c android.intent.category.LAUNCHER 1
        #   Stop    -> am force-stop <pkg>
        #   OpenUri -> am start -a android.intent.action.VIEW -d <uri> [-p <pkg>]
        #   Rotate  -> settings put system accelerometer_rotation / user_rotation
        #   arguments are passed as an argv list, never through a shell string
        raise NotImplementedError
