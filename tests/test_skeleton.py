from support import node, screen_of

from agent_phone.core.snapshot.budget import fit
from agent_phone.core.snapshot.snapshot import SnapshotId
from agent_phone.core.snapshot.surface import select_surface
from agent_phone.core.snapshot.view import Mode, build_view

ID = SnapshotId("t0000")


def message(i):
    return node("android.widget.TextView", text=f"Message {i}", clickable=True)


def shown(view):
    return [(line.role.value, line.name, line.rows, line.folded) for line in view.lines]


def skeleton(screen, mode=Mode.SKELETON):
    return build_view(select_surface(screen), mode)


def test_a_pager_over_a_list_stays_open_down_to_the_list_with_several_rows():
    feed = node("android.widget.ListView", *(message(i) for i in range(5)), scrollable=True)
    page = node("android.widget.ViewPager", node("android.widget.FrameLayout", feed), scrollable=True)
    tab = node("android.widget.Button", text="Home", clickable=True)
    view = skeleton(screen_of(node("android.widget.FrameLayout", page, tab)))
    assert shown(view) == [("pager", "", 1, 0), ("list", "", 5, 5), ("button", "Home", None, 0)]


def test_a_list_with_one_row_is_a_page_and_its_row_is_shown():
    row = node("android.widget.LinearLayout", message(1), message(2))
    only = node("android.widget.ListView", row, scrollable=True)
    view = skeleton(screen_of(node("android.widget.FrameLayout", only)))
    assert [(line.role.value, line.name) for line in view.lines] == [
        ("list", ""),
        ("button", "Message 1"),
        ("button", "Message 2"),
    ]


def test_a_scroll_view_holds_one_child_by_construction_and_still_folds():
    content = node("android.widget.LinearLayout", *(message(i) for i in range(4)))
    scroll = node("android.widget.ScrollView", content, scrollable=True)
    view = skeleton(screen_of(node("android.widget.FrameLayout", scroll)))
    assert shown(view) == [("scroll", "", 1, 4)]


def test_compact_mode_never_looks_through_anything():
    feed = node("android.widget.ListView", *(message(i) for i in range(3)), scrollable=True)
    page = node("android.widget.ViewPager", node("android.widget.FrameLayout", feed), scrollable=True)
    view = skeleton(screen_of(node("android.widget.FrameLayout", page)), Mode.COMPACT)
    assert [(line.role.value, line.folded) for line in view.lines][:2] == [("pager", 0), ("list", 0)]
    assert len(view.lines) == 5


def test_a_page_that_is_too_big_for_the_budget_folds_when_nothing_else_made_it_fit():
    actions = (
        node("android.widget.Button", text=f"Action {i} with a long label", clickable=True)
        for i in range(400)
    )
    page = node("android.widget.ViewPager", node("android.widget.LinearLayout", *actions), scrollable=True)
    screen = screen_of(node("android.widget.FrameLayout", page))
    view = skeleton(screen)
    assert len(view.lines) == 401 and view.lines[0].folded == 0
    fitted = fit(view, ID)
    assert shown(fitted) == [("pager", "", 1, 400)]
