"""Usage: python -I probes/android/redact.py <raw.xml> <out.xml>

Replaces every text, content-desc and hint value with a numbered placeholder unless the
exact value is listed in ui_labels.txt. The same value always maps to the same placeholder
within one file, so tests that match repeated labels still work. Structure, classes,
resource ids, flags and bounds are kept.
"""

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

REDACTED_ATTRS = ("text", "content-desc", "hint")
LABELS = set((Path(__file__).resolve().parent / "ui_labels.txt").read_text().splitlines())

raw, out = Path(sys.argv[1]), Path(sys.argv[2])
tree = ET.parse(raw)
placeholders: dict[str, str] = {}
for node in tree.getroot().iter("node"):
    for attr in REDACTED_ATTRS:
        value = node.get(attr)
        if value and value not in LABELS:
            node.set(attr, placeholders.setdefault(value, f"redacted-{len(placeholders) + 1}"))
tree.write(out, encoding="unicode", xml_declaration=False)
print(f"{out}: {len(placeholders)} distinct values redacted")
