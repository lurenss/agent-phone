"""Compare the text of each field in the server's dump with the text `objInfo` reads for it.

    uv run python -I probes/android/exact_text_probe.py <serial>

The dump goes through the jar's `AccessibilityNodeInfoDumper`, and `objInfo` reads
`UiObject.getText()` for the selector that `address.pin` proves names the field. The probe holds
the device lock, reads the screen once through agent-phone's adapter, and prints one JSON line per
editable node with both texts as code points, the pin and `objInfo` wall time, and whether they
match. It sends no input. Run it through the verify skill's `evidence.py`.
"""

import json
import sys
import time

from agent_phone.adapters.uiautomator2.adb import SubprocessAdb
from agent_phone.adapters.uiautomator2.address import pin
from agent_phone.adapters.uiautomator2.phone import U2Hub
from agent_phone.cli.driver import device_lock
from agent_phone.cli.settings import Settings
from agent_phone.core.act.act import address_of
from agent_phone.core.device import Serial
from agent_phone.core.phone import NotSent
from agent_phone.core.screen import Flag
from agent_phone.core.wait.clock import SystemClock


def points(text: str) -> list[str]:
    return [f"U+{ord(c):04X}" for c in text]


serial = Serial(sys.argv[1])
settings, clock = Settings.from_environment(), SystemClock()
with device_lock(settings, serial, clock, "exact_text_probe"):
    phone = U2Hub(SubprocessAdb(settings.adb), settings.idle_limit_s, clock).open(serial)
    try:
        screen = phone.read()
        for node in screen.nodes:
            if not node.has(Flag.EDITABLE):
                continue
            started = time.monotonic()
            selector = pin(phone._rpc, address_of(screen, node))
            pinned_ms = round((time.monotonic() - started) * 1000)
            if isinstance(selector, NotSent):
                print(json.dumps({"dump": node.attrs.text, "pin": selector.detail}))
                continue
            started = time.monotonic()
            info = phone._rpc.call("objInfo", [selector])
            read_ms = round((time.monotonic() - started) * 1000)
            exact = info.result.get("text") if isinstance(info.result, dict) else None
            print(
                json.dumps(
                    {
                        "dump": node.attrs.text,
                        "dump_points": points(node.attrs.text),
                        "obj_info": exact,
                        "obj_info_points": points(exact) if isinstance(exact, str) else None,
                        "match": exact == node.attrs.text,
                        "pin_ms": pinned_ms,
                        "obj_info_ms": read_ms,
                    },
                    ensure_ascii=False,
                )
            )
    finally:
        phone.close()
