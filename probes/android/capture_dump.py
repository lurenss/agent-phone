"""Usage: uv run python -I probes/android/capture_dump.py <label>

Saves the current screen's full uiautomator2 dump to probes/android/raw/<label>.raw.xml.
The raw file holds private screen content, so git ignores it. Redact it with redact.py
before anything leaves this folder.
"""

import sys
from pathlib import Path

import uiautomator2 as u2

label = sys.argv[1]
out = Path(__file__).resolve().parent / "raw" / f"{label}.raw.xml"
d = u2.connect()
xml = d.dump_hierarchy()
out.write_text(xml)
print(f"{out} package={d.info.get('currentPackageName')} nodes={xml.count('<node')}")
