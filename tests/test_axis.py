"""Which way a collection scrolls, read from what the dump shows of it, and what a sideways swipe
may start on.

A swipe along the axis a collection does not run lands on one of its items, and an item can act
on it: a recents card dismisses an app, a call-log row calls. Every case sends a scroll at act()
on a fake phone and reads what the backend received, so "refused" means nothing was sent."""

import tomllib

import pytest
from fakes import J7_SERIAL, FakePhone, info_for
from support import FakeClock, fixture_screen, node, screen_of

from agent_phone.cli.policy import DEFAULT_POLICY
from agent_phone.core.act.act import act
from agent_phone.core.act.intent import Direction, Request, Scroll
from agent_phone.core.act.ledger import Ledger
from agent_phone.core.context import Context
from agent_phone.core.outcome import Acted, Refused
from agent_phone.core.phone import Swipe
from agent_phone.core.policy.rules import merge, parse_policy
from agent_phone.core.query import Q
from agent_phone.core.refs.resolve import QueryTarget
from agent_phone.core.refs.store import SnapshotStore
from agent_phone.core.screen import Flag
from agent_phone.core.snapshot.capture import capture
from agent_phone.core.snapshot.snapshot import SettleState

POLICY = merge((parse_policy(tomllib.loads(DEFAULT_POLICY.read_text(encoding="utf-8")), "default.toml"),))
RECYCLER = "androidx.recyclerview.widget.RecyclerView"
PAGER = "androidx.viewpager.widget.ViewPager"
HORIZONTAL = "android.widget.HorizontalScrollView"
ALL_WAYS = (Direction.LEFT, Direction.RIGHT, Direction.UP, Direction.DOWN)
ACROSS = {"left": "sent", "right": "sent", "up": "wrong_axis", "down": "wrong_axis"}
DOWN = {"left": "wrong_axis", "right": "wrong_axis", "up": "sent", "down": "sent"}
GRID = {"left": "sent", "right": "sent", "up": "sent", "down": "sent"}


def scroll(root, screen, resource_id, direction):
    """The outcome of one scroll of the collection with `resource_id`, and what the backend got."""
    root = root / f"{resource_id}-{direction.value}"
    root.mkdir()
    info = info_for(J7_SERIAL)
    phone = FakePhone(info, screen)
    ctx = Context(phone, info, None, POLICY, SnapshotStore(root), Ledger(root, info.identity), FakeClock())
    capture(ctx, phone.read(), settled=SettleState.SETTLED)
    outcome = act(ctx, Request(Scroll(QueryTarget(Q(id=resource_id)), direction)))
    return outcome, [permit.action for permit in phone.permits]


def what_happens(root, screen, resource_id="c"):
    """For each direction, 'sent' or the reason of the refusal. A refusal sends nothing."""
    found = {}
    for direction in ALL_WAYS:
        outcome, sent = scroll(root, screen, resource_id, direction)
        if isinstance(outcome, Acted):
            found[direction.value] = "sent"
        else:
            assert isinstance(outcome, Refused) and sent == [], outcome
            found[direction.value] = outcome.details.get("reason", outcome.code.value)
    return found


def collection(*children, resource_id="test.app:id/c", cls=RECYCLER, bounds="[0,200][1080,1700]"):
    return node(cls, *children, scrollable=True, resource_id=resource_id, bounds=bounds)


def screen(*children):
    return screen_of(node("android.widget.FrameLayout", *children, bounds="[0,0][1080,1920]"))


def card(left, width=880, bottom=1700):
    return node(
        "android.widget.FrameLayout",
        node("android.widget.TextView", text=f"App {left}", bounds=f"[{left},200][{left + width},260]"),
        clickable=True,
        bounds=f"[{left},200][{left + width},{bottom}]",
    )


def row(top, bottom):
    return node(
        "android.widget.FrameLayout",
        node("android.widget.TextView", text=f"Row {top}", bounds=f"[0,{top}][800,{top + 60}]"),
        clickable=True,
        bounds=f"[0,{top}][1080,{bottom}]",
    )


def photo(column, line):
    left, top = 360 * column, 300 + 400 * line
    return node(
        "android.widget.Button",
        text=f"Photo {3 * line + column}",
        clickable=True,
        bounds=f"[{left},{top}][{left + 360},{top + 400}]",
    )


def button(label, bounds):
    return node("android.widget.Button", text=label, clickable=True, bounds=bounds)


def strip(bounds):
    """A child that the dump clips to nothing: the card past the edge."""
    return node("android.widget.FrameLayout", visible_to_user=False, bounds=bounds)


def page_of(inner):
    """A pager, named `outer`, whose one page is `inner`."""
    return screen(
        node(
            PAGER,
            inner,
            scrollable=True,
            resource_id="test.app:id/outer",
            bounds="[0,200][1080,1700]",
        )
    )


def shape(name, screen_, expected):
    return pytest.param(screen_, expected, id=name)


SHAPES = [
    shape("two cards side by side", screen(collection(card(100), card(1020))), ACROSS),
    shape("a vertical list", screen(collection(row(200, 700), row(700, 1200), row(1200, 1700))), DOWN),
    shape(
        "a grid of two rows of three",
        screen(collection(*(photo(c, r) for r in range(2) for c in range(3)), bounds="[0,300][1080,1100]")),
        GRID,
    ),
    shape(
        "a grid with a lone footer below it",
        screen(
            collection(
                *(photo(c, r) for r in range(2) for c in range(3)),
                button("More", "[340,1120][740,1200]"),
                bounds="[0,300][1080,1220]",
            )
        ),
        GRID,
    ),
    shape(
        "a vertical list that is the page of a pager",
        page_of(collection(row(200, 700), row(700, 1200), row(1200, 1700))),
        DOWN,
    ),
    shape("a pager", screen(collection(card(0, 1080), cls=PAGER)), ACROSS),
    shape("a horizontal scroll view", screen(collection(card(0, 1080), cls=HORIZONTAL)), ACROSS),
    shape(
        "a card whose next card is clipped to nothing at the right edge",
        screen(collection(card(40, 1000), strip("[1080,200][1080,1700]"))),
        ACROSS,
    ),
    shape(
        "a card whose previous card is clipped to nothing at the left edge",
        screen(collection(card(40, 1000), strip("[0,200][0,1700]"))),
        ACROSS,
    ),
    shape(
        "an empty strip below the rows, level with none of them",
        screen(collection(row(200, 700), row(700, 1200), strip("[1080,1700][1080,1900]"))),
        DOWN,
    ),
    shape(
        "one card in a row, 81 % wide",
        screen(collection(card(100, 880))),
        ACROSS,
    ),
    shape(
        "one card in a row, exactly 90 % wide",
        screen(collection(card(54, 972))),
        ACROSS,
    ),
    shape(
        "one card in a row, exactly 75 % tall",
        screen(collection(card(100, 880, bottom=1325))),
        ACROSS,
    ),
    shape("one child that spans the whole width", screen(collection(card(0, 1080))), DOWN),
    shape("one child that spans 92 % of the width", screen(collection(card(40, 1000))), DOWN),
    shape("one child with space on one side only", screen(collection(card(0, 880))), DOWN),
    shape("one child that fills 70 % of the height", screen(collection(card(100, 880, bottom=1250))), DOWN),
    shape(
        "the inner list of a pager, one page in view",
        page_of(
            collection(node("android.widget.FrameLayout", bounds="[0,200][1080,1700]")),
        ),
        ACROSS,
    ),
    shape(
        "two cards side by side with a footer below them",
        screen(
            collection(
                card(100),
                card(1020),
                button("Close all", "[340,1720][740,1800]"),
                bounds="[0,200][1080,1820]",
            )
        ),
        ACROSS,
    ),
    shape(
        "a row of three photos and one more below them",
        screen(collection(*(photo(c, 0) for c in range(3)), photo(0, 1), bounds="[0,300][1080,1100]")),
        ACROSS,
    ),
]


@pytest.mark.parametrize(("screen_", "expected"), SHAPES)
def test_a_collection_scrolls_along_the_axis_it_runs_and_is_refused_across_it(tmp_path, screen_, expected):
    got = what_happens(tmp_path, screen_)
    assert got == expected, f"the intent requires {expected} for a collection of this shape; got {got}"


def test_the_one_page_of_a_vertical_feed_of_videos_still_reads_as_running_down(tmp_path):
    """The known limit. A sideways collection that attaches one full-width child and shows no other
    sign passes as a list: nothing in the dump tells its one page from a page of a vertical feed."""
    got = what_happens(tmp_path, screen(collection(card(0, 1080))))
    assert got == DOWN, got


def feed_of_the_j7():
    return fixture_screen("ig-feed")


NAV_PAGER = "swipeable_nav_view_pager_inner_recycler_view"
TELL_TO_TAP = "tap the tab or button"


def test_a_sideways_swipe_of_a_pager_over_a_list_that_covers_it_is_refused_with_the_tab_to_tap(tmp_path):
    feed = feed_of_the_j7()
    for rid in ("swipeable_tab_view_pager", NAV_PAGER):
        outcome, sent = scroll(tmp_path, feed, rid, Direction.LEFT)
        assert sent == [], (
            f"the swipe starts on a row of the feed's list, which a sideways swipe can act on: {sent}"
        )
        assert isinstance(outcome, Refused) and outcome.details == {"reason": "wrong_axis"}, outcome
        assert TELL_TO_TAP in outcome.message.lower(), outcome.message


def test_the_nav_pager_of_the_j7_feed_runs_across_so_an_up_or_down_scroll_of_it_is_refused(tmp_path):
    outcome, sent = scroll(tmp_path, feed_of_the_j7(), NAV_PAGER, Direction.DOWN)
    assert sent == [], f"the finger moving up over the card is the swipe that dismisses: {sent}"
    assert isinstance(outcome, Refused) and outcome.details == {"reason": "wrong_axis"}, outcome
    assert "left or right" in outcome.message


def test_the_feeds_own_list_is_refused_sideways(tmp_path):
    outcome, sent = scroll(tmp_path, feed_of_the_j7(), "list", Direction.LEFT)
    assert sent == [] and isinstance(outcome, Refused) and outcome.details == {"reason": "wrong_axis"}


def row_under(screen_, point):
    """The words of the clickable row that holds `point`, or None."""
    rows = [n for n in screen_.nodes if n.attrs.bounds.contains(point) and n.has(Flag.CLICKABLE)]
    return next((m.attrs.text for m in screen_.subtree(rows[-1].id) if m.attrs.text), None) if rows else None


GAP_BETWEEN_ROWS = page_of(collection(row(200, 600), row(800, 1700)))
NO_GAP = page_of(collection(row(200, 700), row(700, 1200), row(1200, 1700)))
A_TRAY = page_of(collection(card(100), card(1020)))


@pytest.mark.parametrize("direction", [Direction.LEFT, Direction.RIGHT])
def test_a_pager_whose_page_list_leaves_no_clear_height_refuses_a_sideways_swipe(tmp_path, direction):
    outcome, sent = scroll(tmp_path, NO_GAP, "outer", direction)
    assert sent == [], (
        f"the intent requires wrong_axis: {sent} starts on the row {row_under(NO_GAP, sent[0].start)!r}, "
        "a sideways swipe on a list that runs down"
    )
    assert isinstance(outcome, Refused) and outcome.details == {"reason": "wrong_axis"}, outcome
    assert TELL_TO_TAP in outcome.message.lower(), outcome.message


@pytest.mark.parametrize("direction", [Direction.LEFT, Direction.RIGHT])
def test_a_sideways_swipe_of_a_pager_keeps_to_the_gap_between_the_rows_of_its_page(tmp_path, direction):
    outcome, sent = scroll(tmp_path, GAP_BETWEEN_ROWS, "outer", direction)
    assert isinstance(outcome, Acted) and isinstance(sent[0], Swipe), outcome
    swipe = sent[0]
    assert swipe.start.y == swipe.end.y, "a sideways swipe stays level"
    assert row_under(GAP_BETWEEN_ROWS, swipe.start) is None, (
        f"the swipe starts on the row {row_under(GAP_BETWEEN_ROWS, swipe.start)!r}"
    )


def test_a_page_whose_list_runs_across_leaves_a_sideways_swipe_at_the_middle(tmp_path):
    outcome, sent = scroll(tmp_path, A_TRAY, "outer", Direction.LEFT)
    assert isinstance(outcome, Acted) and sent[0].start.y == 950, "a tray of cards is no list that runs down"


def test_an_up_or_down_swipe_of_a_pager_is_refused_whatever_its_page_is(tmp_path):
    for screen_ in (NO_GAP, GAP_BETWEEN_ROWS, A_TRAY):
        (tmp_path / str(id(screen_))).mkdir()
        outcome, sent = scroll(tmp_path / str(id(screen_)), screen_, "outer", Direction.DOWN)
        assert sent == [] and isinstance(outcome, Refused) and outcome.details == {"reason": "wrong_axis"}
