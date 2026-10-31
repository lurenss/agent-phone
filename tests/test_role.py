import pytest
from support import fixture_screen, labelled, node, screen_of

from agent_phone.core.role import Role, is_actionable, role_of


@pytest.mark.parametrize(
    ("cls", "attrs", "role"),
    [
        ("android.widget.ImageView", {"clickable": True}, Role.BUTTON),
        ("android.view.View", {"clickable": True}, Role.BUTTON),
        ("android.widget.TextView", {"long_clickable": True}, Role.BUTTON),
        ("android.widget.TextView", {}, Role.TEXT),
        ("android.widget.EditText", {}, Role.TEXT_FIELD),
        ("android.widget.LinearLayout", {"checkable": True, "clickable": True}, Role.CHECKBOX),
        ("android.widget.Switch", {"checkable": True}, Role.SWITCH),
        ("android.widget.FrameLayout", {"scrollable": True}, Role.SCROLL),
        ("androidx.recyclerview.widget.RecyclerView", {"scrollable": True}, Role.LIST),
        ("android.support.v7.widget.RecyclerView", {}, Role.LIST),
        ("android.widget.SeekBar", {}, Role.SLIDER),
        ("android.widget.FrameLayout", {}, Role.GROUP),
    ],
)
def test_role_comes_from_flags_first_and_class_second(cls, attrs, role):
    assert role_of(screen_of(node(cls, **attrs)).nodes[0].attrs) is role


@pytest.mark.parametrize(
    ("cls", "attrs", "actionable"),
    [
        ("android.widget.Button", {"clickable": True}, True),
        ("android.widget.Button", {"clickable": True, "enabled": False}, True),
        ("android.widget.Button", {"clickable": True, "visible_to_user": False}, False),
        ("android.widget.FrameLayout", {"scrollable": True}, True),
        ("android.widget.SeekBar", {}, True),
        ("android.widget.EditText", {}, True),
        ("android.widget.TextView", {}, False),
        ("android.widget.Button", {}, False),
    ],
)
def test_actionable_nodes_are_visible_consumers_scrollers_fields_and_sliders(cls, attrs, actionable):
    attrs_ = screen_of(node(cls, **attrs)).nodes[0].attrs
    assert is_actionable(attrs_, role_of(attrs_)) is actionable


def test_static_text_in_a_fixture_is_not_actionable():
    settings = fixture_screen("settings-home")
    title = labelled(settings, "Settings")
    assert not is_actionable(title.attrs, role_of(title.attrs))
