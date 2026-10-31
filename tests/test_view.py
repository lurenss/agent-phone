import pytest
from support import FIXTURES, consumer_of, fixture_screen, labelled, node, screen_of

from agent_phone.core.geometry import Rect
from agent_phone.core.outcome import ErrorCode, Refusal
from agent_phone.core.role import Role
from agent_phone.core.screen import Flag, Screen
from agent_phone.core.snapshot.budget import BUDGET_BYTES, ENVELOPE_RESERVE, encoded_size, fit, render
from agent_phone.core.snapshot.snapshot import SnapshotId
from agent_phone.core.snapshot.surface import select_surface
from agent_phone.core.snapshot.view import Mode, State, build_view

ID = SnapshotId("t0000")


def compact(screen, root=None):
    return build_view(select_surface(screen, root=root), Mode.COMPACT)


def line_for(view, node_id):
    return view.lines[view.nodes.index(node_id)]


def test_a_settings_tile_is_one_ref_named_by_its_title_with_its_summary_as_detail():
    settings = fixture_screen("settings-home")
    title = labelled(settings, "Connections")
    summary = labelled(settings, "Wi-Fi, Bluetooth, Data usage, Airplane mode")
    tile = consumer_of(settings, title)
    view = compact(settings)
    line = line_for(view, tile.id)
    assert (line.role, line.name) == (Role.BUTTON, "Connections")
    assert line.ref is not None and line.detail.startswith("Wi-Fi, Bluetooth, Data usage")
    assert title.id not in view.nodes and summary.id not in view.nodes


def test_a_business_suite_button_with_empty_text_takes_its_childs_label():
    mbs = fixture_screen("mbs-home")
    label = labelled(mbs, "Edit profile")
    button = consumer_of(mbs, label)
    assert Flag.CLICKABLE in button.attrs.flags and button.attrs.text == button.attrs.content_desc == ""
    view = compact(mbs)
    line = line_for(view, button.id)
    assert line.ref is not None and line.name == "Edit profile"
    assert label.id not in view.nodes


def test_static_text_gets_a_line_but_no_ref():
    settings = fixture_screen("settings-home")
    line = line_for(compact(settings), labelled(settings, "Settings").id)
    assert (line.ref, line.role, line.name) == (None, Role.TEXT, "Settings")


def test_the_shade_wrappers_fold_into_their_tiles():
    shade = fixture_screen("notification-shade")
    tile = labelled(shade, "Airplane,mode,Off.,Button")
    wrapper = next(a for a in shade.ancestors(tile.id) if Flag.CLICKABLE in a.attrs.flags)
    assert (tile.attrs.bounds, wrapper.attrs.bounds) == (Rect(998, 203, 1114, 307), Rect(998, 197, 1114, 313))
    wrappers = [
        n
        for n in shade.nodes
        if n.attrs.class_name == "android.widget.LinearLayout" and n.has(Flag.CLICKABLE)
    ]
    view = compact(shade)
    line = line_for(view, tile.id)
    assert line.ref is not None and line.name == "Airplane mode Off."
    assert len(wrappers) == 10 and not {w.id for w in wrappers} & set(view.nodes)
    assert sorted(view.refs) == list(range(1, len(view.refs) + 1))


def test_a_text_that_repeats_the_line_above_it_prints_once():
    mbs = fixture_screen("mbs-home")
    assert [line.name for line in compact(mbs).lines].count("See more") == 1


@pytest.mark.parametrize("name", FIXTURES)
def test_each_compact_snapshot_fits_the_budget_without_cutting(name):
    view = compact(fixture_screen(name))
    fitted = fit(view, ID)
    assert fitted == view
    assert encoded_size(render(fitted, ID)) < BUDGET_BYTES


def test_a_ref_keeps_its_number_in_compact_skeleton_and_drill_down():
    settings = fixture_screen("settings-home")
    tiles = next(n for n in settings.nodes if n.attrs.resource_id.endswith(":id/dashboard_container"))
    display = consumer_of(settings, labelled(settings, "Display"))
    whole, drilled = compact(settings), compact(settings, root=tiles.id)
    skeleton = build_view(select_surface(settings), Mode.SKELETON)
    assert line_for(whole, display.id).ref == line_for(drilled, display.id).ref == 7
    assert (
        line_for(whole, tiles.id).ref == line_for(skeleton, tiles.id).ref == line_for(drilled, tiles.id).ref
    )


def test_the_skeleton_hides_collection_rows_and_counts_them():
    settings = fixture_screen("settings-home")
    tiles = next(n for n in settings.nodes if n.attrs.resource_id.endswith(":id/dashboard_container"))
    skeleton = build_view(select_surface(settings), Mode.SKELETON)
    line = line_for(skeleton, tiles.id)
    assert (line.rows, line.folded) == (4, 4)
    assert not any(
        n.attrs.resource_id.endswith(":id/dashboard_tile") for n in map(settings.node, skeleton.nodes)
    )
    assert set(skeleton.refs) == {line.ref for line in skeleton.lines if line.ref is not None}


def long_list(rows):
    items = [
        node("android.widget.TextView", text=f"Message number {i} with a long preview", clickable=True)
        for i in range(rows)
    ]
    return screen_of(
        node(
            "android.widget.FrameLayout",
            node("android.widget.ListView", *items, scrollable=True),
            bounds="[0,0][1080,1920]",
        )
    )


def test_fitting_a_long_list_keeps_its_ref_and_counts_what_it_cut():
    screen = long_list(300)
    view = compact(screen)
    fitted = fit(view, ID)
    assert encoded_size(render(view, ID)) > BUDGET_BYTES
    assert encoded_size(render(fitted, ID)) <= BUDGET_BYTES - ENVELOPE_RESERVE
    collection = fitted.lines[0]
    assert collection.ref == 1 and collection.rows == 300 and collection.folded > 0
    assert len(fitted.lines) + collection.folded == len(view.lines)
    assert set(fitted.refs) == {line.ref for line in fitted.lines if line.ref is not None}


def test_a_secret_field_shows_its_state_and_never_its_text():
    screen = screen_of(
        node(
            "android.widget.FrameLayout",
            node("android.widget.EditText", text="hunter2", hint="Password", password=True, clickable=True),
            node("android.widget.EditText", text="lorenzo", hint="Username", clickable=True),
        )
    )
    secret, plain = compact(screen).lines
    assert (secret.name, secret.value, State.SECRET in secret.states) == ("Password", "", True)
    assert (plain.name, plain.value) == ("Username", "lorenzo")
    assert "hunter2" not in "".join(render(compact(screen), ID))


def test_full_mode_prints_every_node_of_the_surface():
    mbs = fixture_screen("mbs-home")
    surface = select_surface(mbs)
    assert len(build_view(surface, Mode.FULL).lines) == len(mbs.subtree(surface.window.root))


def test_the_surface_is_the_active_window_and_lists_the_others():
    surface = select_surface(fixture_screen("ig-feed"))
    assert surface.window.package == "com.instagram.android"
    assert [(w.package, w.bounds) for w in surface.others] == [("com.android.systemui", Rect(0, 0, 1080, 63))]
    assert surface.others[0].nodes > 0
    assert (surface.keyboard, surface.dialog) == (False, False)


def test_a_window_smaller_than_the_display_is_a_dialog_and_a_keyboard_is_noticed():
    screen = screen_of(
        node("android.widget.FrameLayout", bounds="[90,600][990,1300]"),
        node("android.widget.FrameLayout", package="test.keyboard", bounds="[0,1200][1080,1920]"),
        ime_package="test.keyboard",
    )
    surface = select_surface(screen)
    assert (surface.dialog, surface.keyboard) == (True, True)


def test_no_active_window_is_no_surface():
    screen = fixture_screen("settings-home")
    windowless = Screen(screen.display, screen.rotation, (), (), ())
    with pytest.raises(Refusal) as refused:
        select_surface(windowless)
    assert refused.value.code is ErrorCode.NO_SURFACE
