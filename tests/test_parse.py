import xml.etree.ElementTree as ET

import pytest
from support import FIXTURES, J7, fixture_screen, fixture_xml, node, screen_of

from agent_phone.adapters.uiautomator2.parse import parse_hierarchy
from agent_phone.core.device import Package
from agent_phone.core.geometry import Rect, Rotation, Size
from agent_phone.core.outcome import ErrorCode, Refusal
from agent_phone.core.screen import Attrs, Flag, NodeSpec, Screen, WindowKind, WindowSpec


def test_windows_keep_dump_order_and_the_first_is_active():
    ig = fixture_screen("ig-feed")
    assert [(w.package, w.kind, w.active) for w in ig.windows] == [
        ("com.instagram.android", WindowKind.APPLICATION, True),
        ("com.android.systemui", WindowKind.SYSTEM, False),
    ]
    assert ig.active_window() == ig.windows[0]


def test_landscape_dump_swaps_the_natural_display():
    settings = fixture_screen("settings-home")
    assert settings.rotation is Rotation.LEFT
    assert settings.display == Size(1920, 1080)
    assert settings.windows[0].bounds == Rect(0, 0, 1920, 1080)


def test_pulled_down_shade_is_the_only_window_and_a_system_one():
    shade = fixture_screen("notification-shade")
    assert [(w.package, w.kind, w.active) for w in shade.windows] == [
        ("com.android.systemui", WindowKind.SYSTEM, True)
    ]


@pytest.mark.parametrize("name", FIXTURES)
def test_every_dump_node_lands_in_the_arena_once(name):
    screen = fixture_screen(name)
    assert len(screen.nodes) == len(ET.fromstring(fixture_xml(name)).findall(".//node"))
    for node_ in screen.nodes:
        assert screen.nodes[node_.id] is node_
        assert all(screen.node(child).parent == node_.id for child in node_.children)
        descendants = sum(len(screen.subtree(child)) for child in node_.children)
        assert len(screen.subtree(node_.id)) == 1 + descendants
        assert all(below.window == node_.window for below in screen.subtree(node_.id))
        top = [node_.id, *(a.id for a in screen.ancestors(node_.id))][-1]
        assert top == screen.window_of(node_.id).root


def test_attributes_and_flags_come_from_the_dump():
    settings = fixture_screen("settings-home")
    search = next(n for n in settings.nodes if n.attrs.content_desc == "Search")
    assert search.attrs.class_name == "android.widget.Button"
    assert search.attrs.bounds == Rect(1648, 0, 1775, 147)
    assert search.attrs.flags == {
        Flag.CLICKABLE,
        Flag.LONG_CLICKABLE,
        Flag.FOCUSABLE,
        Flag.ENABLED,
        Flag.VISIBLE,
    }
    assert isinstance(search.attrs.drawing_order, int)


def test_edit_text_is_editable_and_a_missing_hint_or_drawing_order_is_absent():
    screen = screen_of(node("android.widget.FrameLayout", node("android.widget.EditText", text="typed")))
    field = screen.nodes[1]
    assert Flag.EDITABLE in field.attrs.flags
    assert field.attrs.hint == ""
    assert field.attrs.drawing_order is None
    assert Flag.EDITABLE not in screen.nodes[0].attrs.flags


def test_the_default_keyboard_window_is_an_input_method():
    screen = screen_of(
        node("android.widget.FrameLayout"),
        node("android.widget.FrameLayout", package="test.keyboard"),
        ime_package=Package("test.keyboard"),
    )
    assert [w.kind for w in screen.windows] == [WindowKind.APPLICATION, WindowKind.INPUT_METHOD]


@pytest.mark.parametrize(
    ("xml", "code"),
    [
        ("<hierarchy rotation='0'><node", ErrorCode.TRANSPORT),
        ("<hierarchy rotation='7'><node class='V' bounds='[0,0][1,1]'/></hierarchy>", ErrorCode.TRANSPORT),
        ("<hierarchy rotation='0'><node class='V' bounds='[0,0][a,b]'/></hierarchy>", ErrorCode.TRANSPORT),
        ("<hierarchy rotation='0'/>", ErrorCode.NO_SURFACE),
    ],
)
def test_a_dump_that_does_not_parse_is_refused(xml, code):
    with pytest.raises(Refusal) as refused:
        parse_hierarchy(xml, J7, ime_package=None)
    assert refused.value.code is code


def test_two_active_windows_are_refused():
    attrs = Attrs("V", "test.app", "", "", "", "", Rect(0, 0, 1, 1), frozenset(), None, None)
    window = WindowSpec(
        Package("test.app"), WindowKind.APPLICATION, Rect(0, 0, 1, 1), True, None, NodeSpec(attrs, ())
    )
    with pytest.raises(Refusal) as refused:
        Screen.build(J7, Rotation.NATURAL, [window, window])
    assert refused.value.code is ErrorCode.INTERNAL
