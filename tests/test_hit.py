"""The hit plan: a touch goes to whatever is at its point, so a tap is planned only at a point
whose receiver is exactly the target, in the window that has focus, under no other window."""

import pytest
from support import consumer_of, fixture_screen, labelled, node, screen_of

from agent_phone.core.act.hit import Ambiguous, context_labels, plan_point, receiver_at
from agent_phone.core.geometry import Point
from agent_phone.core.outcome import ErrorCode, Refusal

STATUS_BAR = node("android.widget.FrameLayout", package="com.android.systemui", bounds="[0,0][1080,63]")
KEYBOARD = node(
    "android.widget.FrameLayout",
    node("android.widget.Button", text="Space", clickable=True, bounds="[0,1500][1080,1920]"),
    package="test.keyboard",
    bounds="[0,1200][1080,1920]",
)


def app(*children: str) -> str:
    return node("android.widget.FrameLayout", *children, bounds="[0,0][1080,1920]")


def button(label: str, bounds: str, **attrs: object) -> str:
    return node("android.widget.Button", text=label, clickable=True, bounds=bounds, **attrs)


def refused(call) -> Refusal:
    with pytest.raises(Refusal) as raised:
        call()
    return raised.value


def test_a_settings_tile_is_tapped_at_its_center_and_receives_the_touch():
    settings = fixture_screen("settings-home")
    tile = consumer_of(settings, labelled(settings, "Display"))
    point = plan_point(settings, tile)
    assert point == tile.attrs.bounds.center()
    assert receiver_at(settings, settings.window_of(tile.id), point) == tile.id


def test_nothing_covers_a_dialog_over_an_app_because_the_app_is_not_in_the_dump():
    screen = fixture_screen("dialog-over-app")
    assert [w.package for w in screen.windows if not w.active] == ["com.android.systemui"]
    for label in ("Deny", "Allow"):
        target = consumer_of(screen, labelled(screen, label))
        assert plan_point(screen, target) == target.attrs.bounds.center()


def test_the_keyboard_covers_what_lies_under_it_and_nothing_else():
    screen = screen_of(
        app(button("Under", "[0,1300][1080,1400]"), button("Above", "[0,800][1080,900]")),
        KEYBOARD,
        ime_package="test.keyboard",
    )
    error = refused(lambda: plan_point(screen, labelled(screen, "Under")))
    assert error.code is ErrorCode.OCCLUDED and "input_method" in error.details["blocked_by"][0]
    above = labelled(screen, "Above")
    assert plan_point(screen, above) == above.attrs.bounds.center()


def test_a_point_under_the_status_bar_is_skipped_for_one_below_it():
    screen = screen_of(app(button("Back", "[0,0][200,100]")), STATUS_BAR)
    target = labelled(screen, "Back")
    point = plan_point(screen, target)
    assert point == Point(50, 75) and not screen.windows[1].bounds.contains(point)


def test_overlapping_elements_whose_order_is_unknown_are_never_tapped():
    unordered = screen_of(app(button("Low", "[0,0][400,400]"), button("High", "[0,0][400,400]")))
    assert isinstance(receiver_at(unordered, unordered.windows[0], Point(200, 200)), Ambiguous)
    assert refused(lambda: plan_point(unordered, labelled(unordered, "Low"))).code is ErrorCode.OCCLUDED
    ordered = screen_of(
        app(
            button("Low", "[0,0][400,400]", drawing_order=1),
            button("High", "[0,0][400,400]", drawing_order=2),
        )
    )
    high = labelled(ordered, "High")
    assert plan_point(ordered, high) == high.attrs.bounds.center()
    assert refused(lambda: plan_point(ordered, labelled(ordered, "Low"))).code is ErrorCode.OCCLUDED


def test_a_row_is_tapped_beside_the_button_it_holds_and_the_button_takes_its_own_point():
    screen = screen_of(
        app(
            node(
                "android.widget.LinearLayout",
                button("Delete", "[440,0][640,100]"),
                text="Row",
                clickable=True,
                bounds="[0,0][1080,100]",
            )
        )
    )
    row, delete = labelled(screen, "Row"), labelled(screen, "Delete")
    assert plan_point(screen, row) == Point(270, 25)
    assert receiver_at(screen, screen.windows[0], row.attrs.bounds.center()) == delete.id


def test_a_window_without_focus_or_an_element_with_no_area_takes_no_tap():
    screen = screen_of(app(button("Here", "[0,500][100,600]")), app(button("There", "[0,500][100,600]")))
    assert refused(lambda: plan_point(screen, labelled(screen, "There"))).code is ErrorCode.OCCLUDED
    flat = screen_of(app(button("Flat", "[0,500][100,500]")))
    assert refused(lambda: plan_point(flat, labelled(flat, "Flat"))).code is ErrorCode.NOT_ACTIONABLE


def test_the_context_of_a_button_is_the_rest_of_its_window():
    screen = screen_of(
        app(
            node("android.widget.TextView", text="Delete this post?", bounds="[0,0][1080,100]"),
            node(
                "android.widget.Button",
                node("android.widget.TextView", text="OK", bounds="[0,200][540,300]"),
                clickable=True,
                bounds="[0,200][540,300]",
            ),
        )
    )
    ok = consumer_of(screen, labelled(screen, "OK"))
    said = {label.value for label in context_labels(screen, ok)}
    assert "Delete this post?" in said and "OK" not in said
