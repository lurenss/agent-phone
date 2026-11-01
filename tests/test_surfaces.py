import pytest
from fakes import J7_SERIAL, FakeHub, invoke
from support import fixture_screen, node, screen_of

from agent_phone.core.device import Connected
from agent_phone.core.outcome import ErrorCode, Refusal
from agent_phone.core.snapshot.surface import Pick, select_surface

J7 = Connected(J7_SERIAL, "SM_J730F", ready=True)


def with_keyboard():
    app = node(
        "android.widget.FrameLayout",
        node("android.widget.EditText", hint="Message", clickable=True, bounds="[0,100][1080,200]"),
        package="test.app",
        bounds="[0,0][1080,1920]",
    )
    keyboard = node(
        "android.widget.FrameLayout",
        node(
            "android.widget.Button",
            text="Q",
            clickable=True,
            package="test.keyboard",
            bounds="[0,1500][108,1600]",
        ),
        package="test.keyboard",
        bounds="[0,1500][1080,1920]",
    )
    return screen_of(app, keyboard, ime_package="test.keyboard")


def snapshot(argv, screens, tmp_path):
    return invoke(["snapshot", *argv], FakeHub([J7], screens=screens), tmp_path)


def test_the_dialog_surface_is_the_active_window_when_it_does_not_cover_the_display(tmp_path):
    code, wire = snapshot(["--surface", "dialog"], [fixture_screen("dialog-over-app")], tmp_path)
    assert code == 0 and wire["data"]["dialog"] is True and wire["data"]["app"] == "com.android.settings"
    assert [line.split(" [")[0] for line in wire["data"]["tree"]][1:] == [
        "@" + wire["data"]["id"] + ':e1 button "Deny"',
        "@" + wire["data"]["id"] + ':e2 button "Allow"',
    ]
    assert [other["app"] for other in wire["data"]["others"]] == ["com.android.systemui"]


def test_no_dialog_is_on_screen_when_the_active_window_covers_the_display(tmp_path):
    code, wire = snapshot(["--surface", "dialog"], [fixture_screen("ig-feed")], tmp_path)
    assert code == 1 and wire["error"]["code"] == "NO_SURFACE"
    assert (
        "No dialog is on screen" in wire["error"]["message"]
        and "com.instagram.android" in wire["error"]["message"]
    )
    assert (wire["delivery"], wire["retry"]) == ("not_delivered", "safe")


def test_the_keyboard_surface_is_the_input_method_window(tmp_path):
    code, wire = snapshot(["--surface", "keyboard"], [with_keyboard()], tmp_path)
    assert code == 0 and wire["data"]["app"] == "test.keyboard" and wire["data"]["window"] == "input_method"
    assert wire["data"]["tree"][0].split(" [")[0].endswith('button "Q"')
    assert [other["app"] for other in wire["data"]["others"]] == ["test.app"]


def test_the_default_snapshot_notes_that_a_keyboard_is_up_without_describing_it(tmp_path):
    code, wire = snapshot([], [with_keyboard()], tmp_path)
    assert wire["data"]["keyboard"] is True and wire["data"]["app"] == "test.app"
    assert [other["window"] for other in wire["data"]["others"]] == ["input_method"]


def test_no_keyboard_is_on_screen_when_no_window_belongs_to_the_input_method(tmp_path):
    code, wire = snapshot(["--surface", "keyboard"], [fixture_screen("ig-feed")], tmp_path)
    assert (
        code == 1
        and wire["error"]["code"] == "NO_SURFACE"
        and wire["error"]["details"] == {"surface": "keyboard"}
    )


def test_the_shade_surface_is_the_full_screen_system_window(tmp_path):
    code, wire = snapshot(["--surface", "shade"], [fixture_screen("notification-shade")], tmp_path)
    assert code == 0 and wire["data"]["app"] == "com.android.systemui" and wire["data"]["window"] == "system"
    assert any("Airplane mode" in line for line in wire["data"]["tree"])


def test_the_status_bar_strip_is_not_a_shade(tmp_path):
    code, wire = snapshot(["--surface", "shade"], [fixture_screen("ig-feed")], tmp_path)
    assert code == 1 and wire["error"]["code"] == "NO_SURFACE"


def test_a_window_id_from_others_describes_that_window(tmp_path):
    screens = [fixture_screen("ig-feed")]
    code, wire = snapshot(["--window", "1"], screens, tmp_path)
    assert code == 0 and wire["data"]["app"] == "com.android.systemui"
    assert [other["id"] for other in wire["data"]["others"]] == [0]
    assert wire["data"]["dialog"] is True


def test_a_window_id_that_is_not_in_the_read_is_no_surface_and_lists_the_windows(tmp_path):
    code, wire = snapshot(["--window", "9"], [fixture_screen("ig-feed")], tmp_path)
    assert code == 1 and wire["error"]["code"] == "NO_SURFACE"
    assert (
        "0 com.instagram.android (application), 1 com.android.systemui (system)" in wire["error"]["message"]
    )


@pytest.mark.parametrize(
    "argv", [["--surface", "dialog", "--window", "0"], ["--surface", "toast"], ["--window", "x"]]
)
def test_a_surface_with_a_window_or_an_unknown_surface_is_invalid_args(tmp_path, argv):
    code, wire = snapshot(argv, [fixture_screen("ig-feed")], tmp_path)
    assert code == 2 and wire["error"]["code"] == "INVALID_ARGS"


def test_all_describes_every_window_under_a_line_that_names_it(tmp_path):
    code, wire = snapshot(["--surface", "all"], [fixture_screen("dialog-over-app")], tmp_path)
    tree = wire["data"]["tree"]
    assert code == 0 and wire["data"]["others"] == []
    assert tree[0] == 'group "com.android.settings" "application" focused [1,1530,1073,1914]'
    assert tree[1].startswith('  text "An app is asking to turn on Bluetooth."')
    heads = [line for line in tree if line.startswith("group ")]
    assert [line.split('"')[1] for line in heads] == ["com.android.settings", "com.android.systemui"]
    assert ["focused" in line for line in heads] == [True, False]


def test_refs_in_an_all_windows_tree_are_numbered_across_windows_without_gaps(tmp_path):
    screen = with_keyboard()
    code, wire = snapshot(["--surface", "all"], [screen], tmp_path)
    refs = [line.split()[0] for line in wire["data"]["tree"] if line.lstrip().startswith("@")]
    snapshot_id = wire["data"]["id"]
    assert refs == [f"@{snapshot_id}:e1", f"@{snapshot_id}:e2"]


def test_select_surface_on_a_screen_with_no_active_window_says_the_screen_may_be_off():
    screen = fixture_screen("settings-home")
    windowless = type(screen)(screen.display, screen.rotation, (), (), ())
    for pick in Pick:
        with pytest.raises(Refusal) as refused:
            select_surface(windowless, pick=pick)
        assert refused.value.code is ErrorCode.NO_SURFACE and "screen may be off" in refused.value.message


def test_settling_on_a_dialog_waits_for_the_dialog_to_appear(tmp_path):
    ig, dialog = fixture_screen("ig-feed"), fixture_screen("dialog-over-app")
    hub = FakeHub([J7], screens=[ig, ig, dialog, dialog])
    code, wire = invoke(["snapshot", "--surface", "dialog", "--settle"], hub, tmp_path)
    assert code == 0 and wire["data"]["settled"] == "settled" and hub.phones[0].reads == 4
    assert wire["data"]["app"] == "com.android.settings"


def test_settling_on_a_dialog_that_never_comes_is_no_surface_at_the_deadline(tmp_path):
    hub = FakeHub([J7], screens=[fixture_screen("ig-feed")])
    code, wire = invoke(["snapshot", "--surface", "dialog", "--settle", "--timeout-ms", "200"], hub, tmp_path)
    assert code == 1 and wire["error"]["code"] == "NO_SURFACE"


def test_all_lists_windows_in_dump_order_so_a_window_id_is_its_place_in_the_tree(tmp_path):
    starting = fixture_screen("app-starting")
    code, wire = snapshot(["--surface", "all"], [starting], tmp_path)
    heads = [line for line in wire["data"]["tree"] if line.startswith("group ")]
    assert [line.split('"')[1] for line in heads] == ["com.android.systemui", "com.android.settings"]
    assert ["focused" in line for line in heads] == [False, True]
    code, wire = snapshot(["--window", "1"], [starting], tmp_path)
    assert wire["data"]["app"] == "com.android.settings" and wire["data"]["others"][0]["id"] == 0


J7_READS = {
    "app-starting": ("com.android.settings", False, ["com.android.systemui"]),
    "dialog-over-app": ("com.android.settings", True, ["com.android.systemui"]),
    "ig-feed": ("com.instagram.android", False, ["com.android.systemui"]),
    "mbs-home": ("com.facebook.pages.app", False, ["com.android.systemui"]),
    "notification-shade": ("com.android.systemui", False, []),
    "settings-home": ("com.android.settings", False, []),
}


@pytest.mark.parametrize("name", J7_READS)
def test_each_j7_dump_has_its_active_window_dialog_flag_and_other_windows(name):
    """The J7's dumps carry no `display-id` and none of their windows is inset by more than a bar,
    so a change to how a dump becomes a screen must leave every row here as it is."""
    surface = select_surface(fixture_screen(name))
    package, dialog, others = J7_READS[name]
    assert (surface.window.package, surface.dialog, [o.package for o in surface.others]) == (
        package,
        dialog,
        others,
    )


IN_BUG_3 = pytest.mark.xfail(
    strict=True, reason="a window that misses the display by a bar or less is not seen as filling it"
)


def one_window(bounds, rotation=0, package="test.app"):
    return screen_of(node("android.widget.FrameLayout", package=package, bounds=bounds), rotation=rotation)


FILLS = [
    pytest.param("[0,0][1080,1920]", 0, id="whole display"),
    pytest.param("[1,0][1079,1919]", 0, id="one pixel short on every side", marks=IN_BUG_3),
    pytest.param(
        "[0,63][1080,1794]", 0, id="J7 app between the status bar and the navigation bar", marks=IN_BUG_3
    ),
    pytest.param("[0,25][1920,1080]", 1, id="Thor app starting below a 25 px strip", marks=IN_BUG_3),
    pytest.param("[1,0][1920,1079]", 1, id="Thor app one pixel short", marks=IN_BUG_3),
    pytest.param("[80,150][1000,1770]", 0, id="dialog with every margin under 8 percent", marks=IN_BUG_3),
]
DOES_NOT_FILL = [
    pytest.param("[1,1530][1073,1914]", 0, id="J7 Bluetooth dialog, A2-7"),
    pytest.param("[87,0][1080,1920]", 0, id="left margin over 8 percent of the width"),
    pytest.param("[0,0][993,1920]", 0, id="right margin over 8 percent of the width"),
    pytest.param("[0,154][1080,1920]", 0, id="top margin over 8 percent of the height"),
    pytest.param("[0,0][1080,1766]", 0, id="bottom margin over 8 percent of the height"),
    pytest.param("[0,0][540,1920]", 0, id="half of the width"),
    pytest.param("[0,0][1240,1079]", 1, id="Thor window over the left 1240 px"),
]


@pytest.mark.parametrize(("bounds", "rotation"), FILLS)
def test_a_window_that_misses_the_display_by_a_bar_or_less_is_not_a_dialog(bounds, rotation):
    dialog = select_surface(one_window(bounds, rotation)).dialog
    assert dialog is False


@pytest.mark.parametrize(("bounds", "rotation"), DOES_NOT_FILL)
def test_a_window_that_misses_the_display_by_more_than_a_bar_is_a_dialog(bounds, rotation):
    dialog = select_surface(one_window(bounds, rotation)).dialog
    assert dialog is True


@IN_BUG_3
def test_the_dialog_surface_does_not_take_an_app_that_the_bars_inset(tmp_path):
    inset = one_window("[0,63][1080,1794]")
    code, wire = snapshot(["--surface", "dialog"], [inset], tmp_path)
    assert code == 1 and wire["error"]["code"] == "NO_SURFACE"


@IN_BUG_3
def test_the_shade_surface_takes_a_system_window_that_is_a_pixel_short_of_the_display(tmp_path):
    shade = one_window("[1,0][1079,1919]", package="com.android.systemui")
    code, wire = snapshot(["--surface", "shade"], [shade], tmp_path)
    assert code == 0 and wire["data"]["app"] == "com.android.systemui"


def test_the_shade_surface_does_not_take_a_system_dialog_that_leaves_the_display_uncovered(tmp_path):
    code, wire = snapshot(
        ["--surface", "shade"], [one_window("[0,0][540,1920]", package="com.android.systemui")], tmp_path
    )
    assert code == 1 and wire["error"]["code"] == "NO_SURFACE"
