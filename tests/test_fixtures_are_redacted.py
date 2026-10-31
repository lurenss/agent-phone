import re
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DUMPS = sorted((ROOT / "tests" / "fixtures" / "dumps").glob("*.xml"))
LABELS = set((ROOT / "probes" / "android" / "ui_labels.txt").read_text().splitlines())
PLACEHOLDER = re.compile(r"redacted-\d+")


def unredacted_values(xml: str) -> list[str]:
    found = []
    for node in ET.fromstring(xml).iter("node"):
        for attr in ("text", "content-desc", "hint"):
            value = node.get(attr)
            if value and value not in LABELS and not PLACEHOLDER.fullmatch(value):
                found.append(value)
    return found


def test_check_catches_a_private_value():
    planted = '<hierarchy><node text="Home" content-desc="someone_private" /></hierarchy>'
    assert unredacted_values(planted) == ["someone_private"]


def test_committed_dumps_hold_only_labels_and_placeholders():
    assert DUMPS, "no fixture dumps found"
    for path in DUMPS:
        assert unredacted_values(path.read_text()) == [], path.name
