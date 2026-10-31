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
