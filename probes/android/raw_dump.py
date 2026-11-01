"""Save the server's full dump of the screen, for offline checks such as `gate_check.py`.

    uv run python -I probes/android/raw_dump.py <serial> <label>

Writes `probes/android/raw/<label>.raw.xml`, which git ignores because it holds private screen
content. It reads through agent-phone's own adapter and holds the device lock, so it never runs
beside another agent-phone process. Run it through the verify skill's `evidence.py` so the read is
recorded. `evidence.py` knows this script as a read, so it needs no `--input`.
"""

import sys
from pathlib import Path

from agent_phone.adapters.uiautomator2.adb import SubprocessAdb
from agent_phone.adapters.uiautomator2.phone import U2Hub, dump_text
from agent_phone.cli.driver import device_lock
from agent_phone.cli.settings import Settings
from agent_phone.core.device import Serial
from agent_phone.core.wait.clock import SystemClock

serial, label = Serial(sys.argv[1]), sys.argv[2]
settings, clock = Settings.from_environment(), SystemClock()
out = Path(__file__).resolve().parent / "raw" / f"{label}.raw.xml"
with device_lock(settings, serial, clock, "raw_dump"):
    phone = U2Hub(SubprocessAdb(settings.adb), settings.idle_limit_s, clock).open(serial)
    try:
        text = dump_text(phone._rpc, serial)
    finally:
        phone.close()
out.parent.mkdir(exist_ok=True)
out.write_text(text)
print(f"{out} {text.count('<node')} nodes")
