import pytest
from support import compact, consumer_of, fixture_screen, labelled, node, screen_of

from agent_phone.core.geometry import Rect
from agent_phone.core.outcome import ErrorCode, Refusal
from agent_phone.core.refs.fingerprint import fingerprints, key_of
from agent_phone.core.snapshot.snapshot import RefToken


def printed_refs_with_id(view, entry):
    screen = view.surface.screen
    return {
        ref: id for ref, id in view.refs.items() if screen.node(id).attrs.resource_id.endswith(f":id/{entry}")
    }


def test_instagram_rows_that_share_outer_container_get_distinct_fingerprints():
    view = compact(fixture_screen("ig-feed"))
    rows = printed_refs_with_id(view, "outer_container")
    assert len(rows) == 4
    prints = fingerprints(view)
    keys = [prints[ref].key for ref in rows]
    assert len(set(keys)) == 4
    assert all(prints[ref].twin is None for ref in rows)


def test_settings_tiles_that_share_a_resource_id_get_distinct_fingerprints():
    view = compact(fixture_screen("settings-home"))
    tiles = printed_refs_with_id(view, "dashboard_tile")
    prints = fingerprints(view)
    assert len(tiles) == 4 and len({prints[ref].key for ref in tiles}) == 4


def test_a_row_key_holds_the_labels_of_the_row():
    ig = fixture_screen("ig-feed")
    row = consumer_of(ig, labelled(ig, "Your story"))
    assert "Your story" in key_of(ig, row).row
    assert key_of(ig, labelled(ig, "Home")).row is None


def test_the_same_button_in_two_rows_is_told_apart_by_its_row():
    def row(author):
        like = node(
            "android.widget.ImageView", content_desc="Like", clickable=True, resource_id="test.app:id/like"
        )
        return node("android.widget.LinearLayout", node("android.widget.TextView", text=author), like)

    screen = screen_of(
        node(
            "android.widget.FrameLayout",
            node("android.widget.ListView", row("ada"), row("bob"), scrollable=True),
        )
    )
    view = compact(screen)
    likes = [ref for ref, id in view.refs.items() if screen.node(id).attrs.content_desc == "Like"]
    prints = fingerprints(view)
    assert len(likes) == 2 and prints[likes[0]].key != prints[likes[1]].key
    assert prints[likes[0]].twin is None and prints[likes[1]].twin is None


def test_identical_nameless_icons_are_twins_identified_by_position():
    icon = "android.widget.ImageView"
    screen = screen_of(
        node(
            "android.widget.FrameLayout",
            node(icon, clickable=True, bounds="[0,0][100,100]"),
            node(icon, clickable=True, bounds="[100,0][200,100]"),
        )
    )
    prints = fingerprints(compact(screen))
    assert prints[1].key == prints[2].key
    assert (prints[1].twin.ordinal, prints[2].twin.ordinal) == (0, 1)
    assert prints[1].twin.bounds == prints[2].twin.bounds == (Rect(0, 0, 100, 100), Rect(100, 0, 200, 100))


def test_a_field_keeps_its_key_while_text_is_typed_and_the_screen_scrolls():
    def screen(text, top):
        field = node(
            "android.widget.EditText",
            text=text,
            hint="Describe your reel",
            clickable=True,
            bounds=f"[0,{top}][1080,{top + 100}]",
        )
        return screen_of(node("android.widget.FrameLayout", field))

    before, after = screen("", 300), screen("my caption", 500)
    assert key_of(before, before.nodes[1]) == key_of(after, after.nodes[1])


def test_a_ref_token_round_trips_through_its_text():
    token = RefToken.parse("@k3x9q:e12")
    assert (token.snapshot, token.number) == ("k3x9q", 12)
    assert str(token) == "@k3x9q:e12"


@pytest.mark.parametrize(
    "text",
    [
        "e12",
        "@e12",
        "@k3x9q:12",
        "@k3x9q:e0",
        "@k3x9q:e-1",
        "@k3x9:e1",
        "@k3x9qq:e1",
        "@k3xiq:e1",
        "@K3X9Q:e1",
        " @k3x9q:e1",
    ],
)
def test_a_ref_token_without_a_valid_snapshot_id_is_rejected(text):
    with pytest.raises(Refusal) as refused:
        RefToken.parse(text)
    assert refused.value.code is ErrorCode.INVALID_ARGS
