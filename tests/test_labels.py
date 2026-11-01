import pytest
from support import checkbox_row, consumer_of, fixture_screen, labelled, node, screen_of

from agent_phone.core.labels import (
    LabelField,
    display_detail,
    display_name,
    normalized,
    stable_name,
    surface_of,
    words,
)
from agent_phone.core.role import Role, role_of


def name_of(screen, node_):
    return display_name(screen, node_, role_of(node_.attrs))


def test_a_settings_tile_is_named_by_its_title_with_its_summary_as_detail():
    settings = fixture_screen("settings-home")
    tile = consumer_of(settings, labelled(settings, "Connections"))
    assert tile.attrs.resource_id.endswith(":id/dashboard_tile")
    assert name_of(settings, tile) == "Connections"
    assert display_detail(settings, tile) == "Wi-Fi, Bluetooth, Data usage, Airplane mode"


def test_a_button_with_empty_text_takes_the_label_of_the_view_inside_it():
    mbs = fixture_screen("mbs-home")
    button = consumer_of(mbs, labelled(mbs, "Edit profile"))
    assert (button.attrs.class_name, button.attrs.text, button.attrs.content_desc) == (
        "android.widget.Button",
        "",
        "",
    )
    assert name_of(mbs, button) == "Edit profile"


def test_the_surface_stops_at_a_nested_touch_consumer():
    ig = fixture_screen("ig-feed")
    row = consumer_of(ig, labelled(ig, "Your story"))
    avatar = next(n for n in ig.subtree(row.id)[1:] if n.attrs.class_name == "android.widget.Button")
    row_values = {label.value for label in surface_of(ig, row).labels}
    avatar_values = {label.value for label in surface_of(ig, avatar).labels}
    assert "Your story" in row_values and avatar.attrs.content_desc not in row_values
    assert avatar.attrs.content_desc in avatar_values and "Your story" not in avatar_values


@pytest.mark.xfail(strict=True, reason="label ownership stops at a checkable node that takes no touch")
def test_a_toggle_that_takes_no_touch_hands_its_words_to_the_row_that_takes_it():
    screen = checkbox_row("Delete all")
    checkbox = labelled(screen, "Delete all")
    row = next(screen.ancestors(checkbox.id))
    assert {label.value for label in surface_of(screen, row).labels} >= {"Delete all"}, (
        "the touch lands on the row, so the gate reads the checkbox's words as the row's"
    )
    assert "Delete all" in {label.value for label in surface_of(screen, checkbox).labels}


def test_the_snapshot_still_prints_a_checkbox_under_its_row_with_its_own_name():
    screen = checkbox_row("Delete all")
    checkbox = labelled(screen, "Delete all")
    row = next(screen.ancestors(checkbox.id))
    assert (name_of(screen, row), name_of(screen, checkbox)) == ("", "Delete all")


def test_a_comma_joined_system_description_reads_as_words():
    shade = fixture_screen("notification-shade")
    tile = labelled(shade, "Airplane,mode,Off.,Button")
    assert name_of(shade, tile) == "Airplane mode Off."
    clear = labelled(shade, "Clear")
    assert (name_of(shade, clear), display_detail(shade, clear)) == ("Clear", "")


def test_a_collection_names_itself_from_its_own_fields_only():
    ig = fixture_screen("ig-feed")
    tray = labelled(ig, "reels tray container")
    assert role_of(tray.attrs) is Role.LIST
    assert (name_of(ig, tray), display_detail(ig, tray)) == ("reels tray container", "")
    settings = fixture_screen("settings-home")
    tiles = next(n for n in settings.nodes if n.attrs.resource_id.endswith(":id/dashboard_container"))
    assert (name_of(settings, tiles), display_detail(settings, tiles)) == ("", "")


def test_a_plain_layout_does_not_repeat_the_text_inside_it():
    mbs = fixture_screen("mbs-home")
    see_more = next(
        n
        for n in mbs.nodes
        if (n.attrs.class_name, n.attrs.content_desc) == ("android.widget.Button", "See more")
    )
    holder = mbs.node(see_more.parent)
    assert holder.attrs.content_desc == holder.attrs.text == ""
    assert name_of(mbs, holder) == ""


def row_screen(inner):
    """A clickable row whose only content is `inner`, which does not consume touch itself."""
    return screen_of(
        node("android.widget.FrameLayout", node("android.widget.LinearLayout", inner, clickable=True))
    )


def test_a_field_is_named_by_its_hint_and_its_text_is_never_its_name():
    screen = row_screen(node("android.widget.EditText", text="my caption", hint="Describe your reel"))
    row, field = screen.nodes[1], screen.nodes[2]
    assert name_of(screen, field) == "Describe your reel"
    assert "my caption" not in (name_of(screen, field), display_detail(screen, field))
    assert "my caption" not in (name_of(screen, row), display_detail(screen, row))


def test_a_field_keeps_its_stable_name_while_text_is_typed():
    names = set()
    for typed in ("", "a", "typed text"):
        screen = row_screen(node("android.widget.EditText", text=typed, hint="Describe your reel"))
        names.add(stable_name(screen, screen.nodes[2], Role.TEXT_FIELD))
    assert names == {"Describe your reel"}


def test_password_text_never_names_the_row_around_it():
    screen = row_screen(node("android.widget.TextView", text="hunter2", password=True))
    row = screen.nodes[1]
    assert "hunter2" not in (name_of(screen, row), display_detail(screen, row))
    assert stable_name(screen, row, role_of(row.attrs)) is None
    shown = row_screen(node("android.widget.TextView", text="hunter2"))
    assert name_of(shown, shown.nodes[1]) == "hunter2"


@pytest.mark.parametrize(
    ("value", "field", "expected"),
    [
        ("com.example:id/row_feed_button_share", LabelField.RESOURCE_ID, ("row", "feed", "button", "share")),
        ("com.example.widget.ShareButton", LabelField.CLASS_NAME, ("share", "button")),
        ("Modalità Aereo", LabelField.TEXT, ("modalità", "aereo")),
        ("Schedule reel,Button", LabelField.CONTENT_DESC, ("schedule", "reel", "button")),
        ("ＯＫ", LabelField.TEXT, ("ok",)),
        ("goLive", LabelField.TEXT, ("go", "live")),
    ],
)
def test_words_split_labels_the_way_policy_phrases_are_split(value, field, expected):
    assert words(value, field) == expected


def test_normalized_collapses_whitespace_and_case():
    assert normalized("  Schedule\n for  LATER ") == "schedule for later"
