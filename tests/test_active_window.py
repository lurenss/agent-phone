"""Which window of the dump has input focus. The dump has no focus attribute. It lists the active
window first when the server knows one (A2-7). A server that started after the screen last changed
knows none, and then it lists the windows by layer, so the status bar comes first (A2-8)."""

import pytest
from fakes import J7_SERIAL, FakeHub, invoke
from support import fixture_screen, node, screen_of

from agent_phone.core.device import Connected
from agent_phone.core.outcome import ErrorCode, Refusal
from agent_phone.core.screen import WindowKind
from agent_phone.core.snapshot.surface import select_surface

BAR = "[0,0][1080,63]"


def status_bar(**attrs):
    return node("android.widget.FrameLayout", package="com.android.systemui", bounds=BAR, **attrs)


def app(package="test.app", bounds="[0,0][1080,1920]"):
    return node("android.widget.FrameLayout", package=package, bounds=bounds)


def actives(screen):
    return [(w.package, w.kind.value) for w in screen.windows if w.active]


def test_the_app_listed_first_is_active_and_the_status_bar_after_it_is_not():
    assert actives(screen_of(app(), status_bar())) == [("test.app", "application")]


def test_an_app_listed_after_the_status_bar_is_active():
    assert actives(screen_of(status_bar(), app())) == [("test.app", "application")]


def test_a_dump_of_only_the_status_bar_has_no_active_window():
    assert actives(screen_of(status_bar())) == []


def test_the_keyboard_is_never_the_active_window_by_elimination():
    keyboard = node("android.widget.FrameLayout", package="test.keyboard", bounds="[0,1200][1080,1920]")
    screen = screen_of(status_bar(), keyboard, app(), ime_package="test.keyboard")
    assert actives(screen) == [("test.app", "application")]


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


J7 = Connected(J7_SERIAL, "SM_J730F", ready=True)


def test_the_dump_of_a_server_with_no_active_window_describes_the_app_and_not_the_status_bar(tmp_path):
    starting = fixture_screen("app-starting")
    assert [w.package for w in starting.windows] == ["com.android.systemui", "com.android.settings"]
    code, wire = invoke(["snapshot", "--settle"], FakeHub([J7], screens=[starting]), tmp_path)
    data = wire["data"]
    assert code == 0 and data["app"] == "com.android.settings" and data["settled"] == "settled"
    assert 'text "Wi-Fi" [147,96,276,177]' in data["tree"]
    assert [other["app"] for other in data["others"]] == ["com.android.systemui"]


def test_a_dump_of_only_the_status_bar_is_no_surface_and_says_an_app_may_be_starting(tmp_path):
    code, wire = invoke(["snapshot"], FakeHub([J7], screens=[screen_of(status_bar())]), tmp_path)
    assert code == 1 and wire["error"]["code"] == "NO_SURFACE"
    assert "an app may be starting" in wire["error"]["message"]
    assert "0 com.android.systemui (system)" in wire["error"]["message"]


def test_settle_waits_out_a_dump_with_no_window_to_describe(tmp_path):
    bare, ready = screen_of(status_bar()), fixture_screen("app-starting")
    hub = FakeHub([J7], screens=[bare, bare, ready, ready])
    code, wire = invoke(["snapshot", "--settle"], hub, tmp_path)
    assert code == 0 and wire["data"]["app"] == "com.android.settings"
    assert wire["data"]["settled"] == "settled" and hub.phones[0].reads == 4


IN_BUG_1 = pytest.mark.xfail(strict=True, reason="the parser keeps the windows of other displays")


def second_display(label="", bounds="[0,0][540,1920]", display=4):
    child = node("android.widget.TextView", text=label, package="test.second_screen", bounds=bounds)
    return node(
        "android.widget.FrameLayout", child, package="test.second_screen", bounds=bounds, display_id=display
    )


@IN_BUG_1
def test_a_window_of_another_display_is_never_active_even_when_it_comes_first():
    screen = screen_of(status_bar(), second_display(), app())
    assert actives(screen) == [("test.app", "application")]


@IN_BUG_1
def test_a_window_of_another_display_is_not_in_the_screen_at_all():
    screen = screen_of(app(), second_display("Elsewhere"))
    assert [w.package for w in screen.windows] == ["test.app"]
    assert [n.attrs.text for n in screen.nodes if n.attrs.text] == []
    assert select_surface(screen).others == ()


@IN_BUG_1
def test_a_dump_of_windows_on_other_displays_only_is_no_surface():
    with pytest.raises(Refusal) as refused:
        screen_of(second_display(), second_display(display=2))
    assert refused.value.code is ErrorCode.NO_SURFACE


def test_a_window_that_names_display_0_is_kept_like_one_that_names_none():
    screen = screen_of(second_display("Here", display=0), app())
    assert [w.package for w in screen.windows] == ["test.second_screen", "test.app"]
    assert actives(screen) == [("test.second_screen", "application")]
