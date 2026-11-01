"""The samsung-j7 dumps: the active window, the dialog flag and the other windows of each, as
`fixtures.py` read them. A fixture's labels are placeholders, so these tests name no label."""

import pytest
from support import fixture_xml

from agent_phone.adapters.uiautomator2.parse import parse_hierarchy
from agent_phone.core.geometry import Size
from agent_phone.core.snapshot.surface import select_surface

NATURAL = Size(1080, 1920)
PINNED = [
    ("samsung-j7-launcher", "com.sec.android.app.launcher", False, ("com.android.systemui",)),
    ("samsung-j7-settings", "com.android.settings", False, ("com.android.systemui",)),
    ("samsung-j7-dialog", "com.android.settings", True, ("com.android.systemui",)),
]


@pytest.mark.parametrize(("dump", "active", "dialog", "others"), PINNED)
def test_the_samsung_j7_dump_reads_as_pinned(dump, active, dialog, others):
    surface = select_surface(parse_hierarchy(fixture_xml(dump), NATURAL, ime_package=None))
    assert surface.window.package == active
    assert surface.dialog is dialog
    assert tuple(other.package for other in surface.others) == others
