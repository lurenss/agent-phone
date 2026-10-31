"""Which window of the dump has input focus. The dump has no focus attribute. It lists the active
window first when the server knows one (A2-7). A server that started after the screen last changed
knows none, and then it lists the windows by layer, so the status bar comes first (A2-8)."""

import pytest
from support import node, screen_of

from agent_phone.core.screen import WindowKind

BAR = "[0,0][1080,63]"
KNOWS_NO_ACTIVE_WINDOW = pytest.mark.xfail(
    strict=True, reason="the first window is marked active even when it is the status bar strip"
)


def status_bar(**attrs):
    return node("android.widget.FrameLayout", package="com.android.systemui", bounds=BAR, **attrs)


def app(package="test.app", bounds="[0,0][1080,1920]"):
    return node("android.widget.FrameLayout", package=package, bounds=bounds)


def actives(screen):
    return [(w.package, w.kind.value) for w in screen.windows if w.active]


def test_the_app_listed_first_is_active_and_the_status_bar_after_it_is_not():
    assert actives(screen_of(app(), status_bar())) == [("test.app", "application")]


@KNOWS_NO_ACTIVE_WINDOW
def test_an_app_listed_after_the_status_bar_is_active():
    assert actives(screen_of(status_bar(), app())) == [("test.app", "application")]


@KNOWS_NO_ACTIVE_WINDOW
def test_a_dump_of_only_the_status_bar_has_no_active_window():
    assert actives(screen_of(status_bar())) == []


@KNOWS_NO_ACTIVE_WINDOW
def test_the_keyboard_is_never_the_active_window_by_elimination():
    keyboard = node("android.widget.FrameLayout", package="test.keyboard", bounds="[0,1200][1080,1920]")
    screen = screen_of(status_bar(), keyboard, app(), ime_package="test.keyboard")
    assert actives(screen) == [("test.app", "application")]


@KNOWS_NO_ACTIVE_WINDOW
def test_a_navigation_bar_down_the_side_is_not_active_either():
    side = node("android.widget.FrameLayout", package="com.android.systemui", bounds="[1800,0][1920,1080]")
    screen = screen_of(side, app(bounds="[0,0][1800,1080]"), rotation=1)
    assert actives(screen) == [("test.app", "application")]


def test_a_system_dialog_that_is_not_a_strip_is_active():
    dialog = node("android.widget.FrameLayout", package="com.android.systemui", bounds="[90,600][990,1300]")
    assert actives(screen_of(dialog, status_bar())) == [("com.android.systemui", "system")]


def test_the_pulled_down_shade_covers_the_display_and_is_active():
    shade = node("android.widget.FrameLayout", package="com.android.systemui", bounds="[0,0][1080,1920]")
    assert actives(screen_of(shade)) == [("com.android.systemui", "system")]


def test_an_application_window_shaped_like_a_strip_is_still_an_application_window():
    overlay = app("test.overlay", BAR)
    screen = screen_of(overlay, app())
    assert actives(screen) == [("test.overlay", "application")]
    assert screen.windows[0].kind is WindowKind.APPLICATION
