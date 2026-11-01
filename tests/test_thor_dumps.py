"""The AYN Thor's dumps: Android 13, an Italian UI, two displays and rotation 1, so the screen is
1920x1080. Every node carries `display-id`, the bottom screen is display 4 and one of its windows is
in every dump, and the root bounds can sit a pixel inside the display. A fixture's labels are
placeholders, so these tests name a node by its bounds."""

import pytest
from fakes import J7_SERIAL, FakeHub, invoke
from support import fixture_xml

from agent_phone.adapters.uiautomator2.parse import parse_hierarchy
from agent_phone.core.act.hit import plan_point
from agent_phone.core.device import Connected
from agent_phone.core.geometry import Rect, Size
from agent_phone.core.screen import Flag, Screen
from agent_phone.core.snapshot.surface import select_surface

THOR_NATURAL = Size(1080, 1920)
BOTTOM_SCREEN_WINDOW = "com.odin.dualscreen.assistant"
PHONE = Connected(J7_SERIAL, "SM_J730F", ready=True)
THOR_DUMPS = ("thor-launcher", "thor-chess", "thor-netflix", "thor-youtube")


def thor(name: str) -> Screen:
    return parse_hierarchy(fixture_xml(name), THOR_NATURAL, ime_package=None)


def clickable_at(screen: Screen, bounds: tuple[int, int, int, int]):
    found = [n for n in screen.nodes if n.attrs.bounds == Rect(*bounds) and n.has(Flag.CLICKABLE)]
    assert len(found) == 1, f"{len(found)} clickable nodes at {bounds}"
    return found[0]


@pytest.mark.parametrize("name", THOR_DUMPS)
def test_a_window_of_the_bottom_screen_is_not_in_the_screen(name):
    screen = thor(name)
    assert BOTTOM_SCREEN_WINDOW not in {w.package for w in screen.windows}
    assert BOTTOM_SCREEN_WINDOW not in {n.attrs.package for n in screen.nodes}
    assert BOTTOM_SCREEN_WINDOW not in {o.package for o in select_surface(screen).others}


LEFT_ICONS = [(57, 524, 358, 751), (57, 751, 358, 978)]
RIGHT_ICON = (1261, 524, 1562, 751)


@pytest.mark.parametrize("icon", [*LEFT_ICONS, RIGHT_ICON])
def test_a_launcher_icon_is_planned_to_its_center_on_either_side_of_the_bottom_screen_window(icon):
    screen = thor("thor-launcher")
    assert plan_point(screen, clickable_at(screen, icon)) == Rect(*icon).center()


@pytest.mark.parametrize(
    ("name", "app"),
    [
        ("thor-launcher", "com.android.launcher3"),
        ("thor-youtube", "com.google.android.youtube"),
        ("thor-chess", "com.chess"),
        ("thor-netflix", "com.netflix.mediaclient"),
    ],
)
def test_the_active_window_is_the_app_whichever_way_the_status_bar_is_inset(name, app):
    assert select_surface(thor(name)).window.package == app


def test_wait_for_an_app_holds_with_that_app_on_the_thor_screen(tmp_path):
    hub = FakeHub([PHONE], screens=[thor("thor-netflix")])
    code, wire = invoke(["wait", "--app", "com.netflix.mediaclient", "--timeout-ms", "200"], hub, tmp_path)
    assert code == 0 and wire["data"]["app"] == "com.netflix.mediaclient"
