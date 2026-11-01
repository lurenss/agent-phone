"""The AYN Thor's dumps: Android 13, an Italian UI, two displays and rotation 1, so the screen is
1920x1080. Every node carries `display-id`, the bottom screen is display 4 and one of its windows is
in every dump, and the root bounds can sit a pixel inside the display. A fixture's labels are
placeholders, so these tests name a node by its bounds."""

import pytest
from support import fixture_xml

from agent_phone.adapters.uiautomator2.parse import parse_hierarchy
from agent_phone.core.act.hit import plan_point
from agent_phone.core.geometry import Rect, Size
from agent_phone.core.screen import Flag, Screen
from agent_phone.core.snapshot.surface import select_surface

THOR_NATURAL = Size(1080, 1920)
BOTTOM_SCREEN_WINDOW = "com.odin.dualscreen.assistant"
THOR_DUMPS = ("thor-launcher", "thor-chess", "thor-netflix", "thor-youtube")

IN_BUG_1 = pytest.mark.xfail(strict=True, reason="the parser keeps the windows of the Thor's bottom screen")


def thor(name: str) -> Screen:
    return parse_hierarchy(fixture_xml(name), THOR_NATURAL, ime_package=None)


def clickable_at(screen: Screen, bounds: tuple[int, int, int, int]):
    found = [n for n in screen.nodes if n.attrs.bounds == Rect(*bounds) and n.has(Flag.CLICKABLE)]
    assert len(found) == 1, f"{len(found)} clickable nodes at {bounds}"
    return found[0]


@pytest.mark.parametrize("name", THOR_DUMPS)
@IN_BUG_1
def test_a_window_of_the_bottom_screen_is_not_in_the_screen(name):
    screen = thor(name)
    assert BOTTOM_SCREEN_WINDOW not in {w.package for w in screen.windows}
    assert BOTTOM_SCREEN_WINDOW not in {n.attrs.package for n in screen.nodes}
    assert BOTTOM_SCREEN_WINDOW not in {o.package for o in select_surface(screen).others}


LEFT_ICONS = [(57, 524, 358, 751), (57, 751, 358, 978)]
RIGHT_ICON = (1261, 524, 1562, 751)


@pytest.mark.parametrize(
    "icon",
    [pytest.param(icon, marks=IN_BUG_1) for icon in LEFT_ICONS] + [RIGHT_ICON],
)
def test_a_launcher_icon_is_planned_to_its_center_on_either_side_of_the_bottom_screen_window(icon):
    screen = thor("thor-launcher")
    assert plan_point(screen, clickable_at(screen, icon)) == Rect(*icon).center()
