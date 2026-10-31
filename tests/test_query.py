import pytest
from support import consumer_of, fixture_screen, labelled, node, screen_of

from agent_phone.core.outcome import ErrorCode, Refusal
from agent_phone.core.query import Match, Q, Query, matches
from agent_phone.core.role import Role


def settings_tile():
    settings = fixture_screen("settings-home")
    return settings, consumer_of(settings, labelled(settings, "Connections"))


def test_a_name_matches_exactly_ignoring_case_and_spacing():
    settings, tile = settings_tile()
    assert matches(Q("Connections"), settings, tile)
    assert matches(Q("  connections "), settings, tile)
    assert not matches(Q("Connection"), settings, tile)
    assert not matches(Q("Wi-Fi"), settings, tile)


def test_a_prefix_and_a_contains_match_the_name():
    settings, tile = settings_tile()
    assert matches(Q("Conn", match=Match.PREFIX), settings, tile)
    assert not matches(Q("nections", match=Match.PREFIX), settings, tile)
    assert matches(Q("nectio", match=Match.CONTAINS), settings, tile)


def test_text_matches_any_word_the_element_shows_including_its_detail():
    settings, tile = settings_tile()
    assert matches(Q(text="airplane", match=Match.CONTAINS), settings, tile)
    assert matches(Q(text="Wi-Fi, Bluetooth, Data usage, Airplane mode"), settings, tile)
    assert not matches(Q(text="airplane"), settings, tile)
    assert not matches(Q(name="airplane", match=Match.CONTAINS), settings, tile)


def test_role_and_resource_id_must_hold_with_the_name():
    settings, tile = settings_tile()
    assert matches(Q("Connections", role=Role.BUTTON, id="dashboard_tile"), settings, tile)
    assert matches(Q(id="com.android.settings:id/dashboard_tile"), settings, tile)
    assert not matches(Q("Connections", role=Role.TEXT), settings, tile)
    assert not matches(Q("Connections", id="dashboard"), settings, tile)


def field(text, **flags):
    return screen_of(
        node("android.widget.FrameLayout", node("android.widget.EditText", text=text, hint="Name", **flags))
    )


def test_value_matches_the_text_typed_in_a_field_and_never_names_it():
    screen = field("lorenzo", clickable=True)
    box = screen.nodes[1]
    assert matches(Q(value="lorenzo"), screen, box)
    assert matches(Q(value="ORE", match=Match.CONTAINS), screen, box)
    assert matches(Q("Name", role=Role.TEXT_FIELD), screen, box)
    assert not matches(Q("lorenzo"), screen, box)


def test_a_secret_field_has_no_value_a_query_can_read():
    screen = field("hunter2", clickable=True, password=True)
    assert not matches(Q(value="hunter2"), screen, screen.nodes[1])
    assert not matches(Q(value="hunter", match=Match.CONTAINS), screen, screen.nodes[1])


def test_a_value_query_matches_nothing_that_holds_no_value():
    settings, tile = settings_tile()
    assert not matches(Q(value="Connections"), settings, tile)


def test_a_query_with_no_field_is_invalid_args():
    with pytest.raises(Refusal) as refused:
        Query()
    assert refused.value.code is ErrorCode.INVALID_ARGS
    with pytest.raises(Refusal):
        Q()


def test_describe_prints_the_fields_that_are_set():
    assert Q("Wi-Fi").describe() == 'name="Wi-Fi"'
    assert Q("Wi", match=Match.PREFIX, role=Role.BUTTON).describe() == 'role=button name^="Wi"'
    assert Q(id="title", text="Wi", match=Match.CONTAINS).describe() == 'id=title text*="Wi"'
