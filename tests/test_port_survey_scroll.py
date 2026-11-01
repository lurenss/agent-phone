"""The survey's scrolls name their target. On Android 15's About-phone page two elements scroll, so a
`scroll down` with no target is `AMBIGUOUS_TARGET`. The fake phone refuses it the same way, and refuses
the ref of an earlier snapshot as `STALE_REF`."""

import pytest
from port_support import Screen, refusal, script
from test_port_card import edited, evidence, written
from test_port_survey import SCREENS, SETTINGS, Phone, checks, react, run
from test_port_survey import phone as survey_phone

status = script("card_status")

SKIPPED = "no scrolling element"


def about_pages(about: tuple[str, ...], after_down: tuple[str, ...] | None = None) -> dict[str, Screen]:
    return SCREENS | {
        "about": Screen(SETTINGS, about),
        "about-down": Screen(SETTINGS, about if after_down is None else after_down),
    }


def phone_with(about: tuple[str, ...], after_down: tuple[str, ...] | None = None) -> Phone:
    return survey_phone(screens=about_pages(about, after_down))


def scrolls(lines: list[dict]) -> list[dict]:
    return [line for line in checks(lines, "input") if line["name"].startswith("scroll")]


NESTED = ("scroll #outer [0,0,1080,2400]", 'list "rows" (4 rows) [0,300,1080,1500]')
TARGETS = [
    pytest.param(NESTED, 1, id="largest-first"),
    pytest.param(NESTED[::-1], 2, id="largest-last"),
    pytest.param(("pager #tabs [0,0,1080,200]", 'grid "tiles" [0,200,1080,2000]'), 2, id="grid-over-pager"),
    pytest.param(('grid "tiles" [0,0,100,100]', "pager #tabs [0,0,1080,2400]"), 2, id="pager-over-grid"),
    pytest.param(
        (
            'button "list" [0,0,1080,2400]',
            'text "scroll" [0,0,1080,2400]',
            'list "rows" [0,300,1080,500]',
            "scroll #x [0,0,100,100]",
        ),
        3,
        id="a-name-is-not-a-role",
    ),
    pytest.param(('list "a" [0,0,100,100]', 'list "b" [0,0,100,100]'), 1, id="a-tie-goes-to-the-first"),
]


@pytest.mark.parametrize(("tree", "chosen"), TARGETS)
def test_each_scroll_names_the_largest_collection_of_the_read_before_it(tmp_path, tree, chosen):
    fake = phone_with(tree)
    code, lines = run(tmp_path, fake)
    assert [step["error"] for step in scrolls(lines)] == [None, None]
    down, up = (words for words in fake.inputs if words[0] == "scroll")
    assert (down[:2], up[:2]) == (("scroll", "down"), ("scroll", "up"))
    assert down[2].endswith(f":e{chosen}") and up[2].endswith(f":e{chosen}")
    assert down[2] != up[2], "each ref is from the read just before its own input"
    assert code == 0


def test_the_scroll_up_uses_the_read_taken_after_the_scroll_down(tmp_path):
    fake = phone_with(NESTED, NESTED[::-1])
    _, lines = run(tmp_path, fake)
    assert [step["error"] for step in scrolls(lines)] == [None, None]
    down, up = (words for words in fake.inputs if words[0] == "scroll")
    assert down[2].endswith(":e1") and up[2].endswith(":e2")


class FailsOnceAfterTheScrollDown(Phone):
    failed = False

    def observe(self, command, words):
        if not self.failed and self.inputs and self.inputs[-1][:2] == ("scroll", "down"):
            self.failed = True
            return refusal(command, self.serial, "TRANSPORT")
        return super().observe(command, words)


def test_a_scroll_up_after_a_failed_read_takes_a_new_read_and_names_its_ref(tmp_path):
    fake = FailsOnceAfterTheScrollDown(
        serial="S1",
        screens=about_pages(NESTED, NESTED[::-1]),
        screen="launcher",
        react=react,
    )
    fake.requests = []
    _, lines = run(tmp_path, fake)
    assert [step["error"] for step in scrolls(lines)] == [None, None]
    assert fake.failed
    up = [words for words in fake.inputs if words[0] == "scroll"][1]
    assert up[2].endswith(":e2"), "the ref is from the new read, and the first one is stale"


def test_a_page_with_nothing_that_scrolls_skips_both_scrolls_and_the_journey_goes_on(tmp_path):
    fake = phone_with(('button "Build number" [0,0,1080,200]',))
    code, lines = run(tmp_path, fake)
    steps = checks(lines, "input")
    assert code == 0 and len(steps) == 9
    down, up = scrolls(lines)
    assert (down.get("skipped"), up.get("skipped")) == (SKIPPED, SKIPPED)
    assert not any(words[0] == "scroll" for words in fake.inputs)
    assert fake.inputs[-2:] == [("press", "back"), ("press", "home")]
    assert not any("scroll" in sent for sent in checks(lines, "inputs")[0]["sent"])


def test_a_skipped_scroll_has_every_field_of_an_input_line_for_the_card_and_sent_nothing(tmp_path):
    _, lines = run(tmp_path, phone_with(('button "Build number" [0,0,1080,200]',)))
    steps = checks(lines, "input")
    skipped = scrolls(lines)[0]
    assert set(skipped) == set(steps[0]) | {"skipped"}
    assert skipped["argv"] == ["scroll", "down"]
    assert all(skipped[key] is None for key in ("delivery", "verified_by", "error", "changed"))


def test_only_the_scroll_whose_page_has_nothing_that_scrolls_is_skipped(tmp_path):
    fake = phone_with(('list "rows" [0,0,1080,2000]',), ('button "Build number" [0,0,1080,200]',))
    _, lines = run(tmp_path, fake)
    down, up = scrolls(lines)
    assert (down.get("skipped"), down["error"], down["delivery"]) == (None, None, "delivered_unverified")
    assert up.get("skipped") == SKIPPED
    assert [words[0] for words in fake.inputs].count("scroll") == 1


SKIPPED_LINE = {"skipped": SKIPPED, "delivery": None, "changed": None}


def test_a_scroll_the_survey_skipped_is_a_limit_that_says_why():
    got, reasons = status.status_of(evidence(survey=edited("input", "scroll down", **SKIPPED_LINE)))
    assert got is status.Status.LIMITS
    assert any("'scroll down' was skipped: no scrolling element" in reason for reason in reasons), reasons


def test_the_card_shows_a_skipped_scroll_as_a_row_of_dashes_and_does_not_count_it_as_sent(tmp_path):
    text = (
        written(tmp_path, evidence(survey=edited("input", "scroll down", **SKIPPED_LINE))) / "demo.md"
    ).read_text()
    assert "| 6 | scroll down | - | - | - | a.prefs | - |" in text
