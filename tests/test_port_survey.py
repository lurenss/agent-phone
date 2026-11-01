"""survey.py on a fake phone behind the real evidence.py. The fake follows the journey: home, Settings,
a dialog, About with a list that scrolls. It refuses an input with no read since the last input, so a
survey that skipped a read would show `OBSERVE_FIRST` on its input lines."""

import json
from pathlib import Path

import pytest
from port_support import FakePhone, Screen, script, shared

survey = script("survey")
calls = shared("device_calls")

LAUNCHER = "com.vendor.home"
SETTINGS = "com.vendor.prefs"
SCREENS = {
    "launcher": Screen(LAUNCHER, ('icon "Maps"', 'icon "Mail"')),
    "settings": Screen(SETTINGS, ('text "Settings"', 'button "Connections"')),
    "dialog": Screen(SETTINGS, ('text "Allow Bluetooth?"', 'button "Allow"'), dialog=True),
    "about": Screen(SETTINGS, ('text "About phone"', 'list "rows" (4 rows)')),
    "about-down": Screen(SETTINGS, ('text "Build number"', 'list "rows" (2 rows)')),
}
BACK = {"dialog": "settings", "about": "settings", "about-down": "settings", "settings": "launcher"}
INPUTS = [
    ["press", "home"],
    ["open-url", "intent:#Intent;action=android.settings.SETTINGS;end"],
    ["open-url", "intent:#Intent;action=android.bluetooth.adapter.action.REQUEST_ENABLE;end"],
    ["press", "back"],
    ["open-url", "intent:#Intent;action=android.settings.DEVICE_INFO_SETTINGS;end"],
    ["scroll", "down"],
    ["scroll", "up"],
    ["press", "back"],
    ["press", "home"],
]


def react(phone: FakePhone, words: tuple[str, ...]) -> str:
    match words:
        case ("press", "home"):
            return "launcher"
        case ("press", "back"):
            return BACK.get(phone.screen, phone.screen)
        case ("open-url", url) if "SETTINGS;end" in url and "DEVICE_INFO" not in url:
            return "settings"
        case ("open-url", url) if "REQUEST_" in url:
            phone.requests.append(url)
            return "dialog" if phone.has_bluetooth else phone.screen
        case ("open-url", url) if "DEVICE_INFO_SETTINGS" in url:
            return "about"
        case ("scroll", "down") if phone.screen == "about":
            return "about-down"
        case ("scroll", "up") if phone.screen == "about-down":
            return "about"
    raise FakePhone.Refused("NOT_FOUND")


class Phone(FakePhone):
    has_bluetooth = True
    dialog_lag = 0

    def observe(self, command, words):
        """A dialog that takes `dialog_lag` reads to show: the reads before it still say Settings."""
        if self.screen == "dialog" and self.dialog_lag:
            self.dialog_lag -= 1
            self.screen = "settings"
            try:
                return super().observe(command, words)
            finally:
                self.screen = "dialog"
        return super().observe(command, words)


def phone(**changes) -> Phone:
    fake = Phone(serial="S1", screens=dict(SCREENS), screen="launcher", react=react)
    fake.requests = []
    for key, value in changes.items():
        setattr(fake, key, value)
    return fake


def run(tmp_path: Path, fake: Phone, **facts) -> tuple[int, list[dict]]:
    document = {"serial": "S1", "awake": True, "bluetooth_on": False} | facts
    (tmp_path / "facts.json").write_text(json.dumps(document))
    code = survey.main([str(tmp_path), "S1", "x"], fake.runner)
    lines = (tmp_path / "survey.jsonl").read_text().splitlines()
    return code, [json.loads(line) for line in lines]


def checks(lines: list[dict], name: str) -> list[dict]:
    return [line for line in lines if line["check"] == name]


def records(tmp_path: Path) -> list[dict]:
    found = [json.loads(p.read_text()) for p in tmp_path.glob("*.json") if p.name != "facts.json"]
    return sorted(found, key=lambda r: r["started_utc"])


def test_the_only_inputs_are_the_journey_in_order_and_none_is_a_tap(tmp_path):
    fake = phone()
    code, lines = run(tmp_path, fake)
    assert code == 0
    assert [list(words) for words in fake.inputs] == INPUTS
    assert not {c[0] for c in fake.commands} & {"click", "set-text", "launch", "stop"}
    sent = [r["argv"][3:] for r in records(tmp_path) if r["input"]]
    assert sent == INPUTS
    assert checks(lines, "inputs")[0]["sent"] == [
        "agent-phone -d S1 " + " ".join(f"'{w}'" if ";" in w else w for w in words) for words in INPUTS
    ]


def test_every_input_follows_a_read_so_none_is_refused_for_want_of_an_observation(tmp_path):
    fake = phone()
    _, lines = run(tmp_path, fake)
    inputs = checks(lines, "input")
    assert [line["error"] for line in inputs] == [None] * 9
    assert all(line["delivery"] == "delivered_unverified" for line in inputs)
    kinds = [c[0] for c in fake.commands]
    for at, kind in enumerate(kinds):
        if kind in ("press", "open-url", "scroll"):
            assert kinds[at - 1] in ("snapshot", "wait")


def test_the_three_screens_are_read_settled_checked_against_the_focus_and_dumped(tmp_path):
    fake = phone()
    _, lines = run(tmp_path, fake)
    reads = {line["screen"]: line for line in checks(lines, "screen_read")}
    assert list(reads) == ["launcher", "settings", "dialog"]
    assert (reads["launcher"]["app"], reads["settings"]["app"], reads["dialog"]["app"]) == (
        LAUNCHER,
        SETTINGS,
        SETTINGS,
    )
    assert [reads[s]["dialog"] for s in reads] == [False, False, True]
    assert all(line["settled"] == "settled" and line["agrees"] is True for line in reads.values())
    assert fake.dumps == ["x-launcher", "x-settings", "x-dialog"]
    assert [line["file"] for line in checks(lines, "raw_dump")] == fake.dumps


def test_each_screen_gets_20_snapshots_and_10_settled_snapshots_summarized(tmp_path):
    fake = phone()
    _, lines = run(tmp_path, fake)
    warm = {line["screen"]: line for line in checks(lines, "warm_snapshot")}
    assert list(warm) == ["launcher", "settings", "dialog"]
    for line in warm.values():
        assert (line["runs"], line["errors"], line["wrong_screen"], line["under_8_kb"]) == (20, 0, 0, True)
    assert warm["dialog"]["tree_lines"] == [2, 2]
    settles = checks(lines, "warm_settle")
    assert [(line["screen"], line["settled"], line["runs"]) for line in settles] == [
        ("launcher", 10, 10),
        ("settings", 10, 10),
        ("dialog", 10, 10),
    ]


def test_the_journey_line_says_what_each_input_changed(tmp_path):
    _, lines = run(tmp_path, phone())
    steps = checks(lines, "input")
    assert [s["name"] for s in steps] == [
        "home",
        "open settings",
        "open dialog",
        "back from the dialog",
        "open about",
        "scroll down",
        "scroll up",
        "back from about",
        "home again",
    ]
    assert [s["after_app"] for s in steps] == [LAUNCHER, SETTINGS, SETTINGS, SETTINGS] + [SETTINGS] * 4 + [
        LAUNCHER
    ]
    assert [s["after_dialog"] for s in steps] == [False, False, True] + [False] * 6
    assert [s["changed"] for s in steps] == [False] + [True] * 8


def test_the_dialog_asks_to_be_discoverable_when_bluetooth_is_on_and_to_turn_on_when_off(tmp_path):
    fake = phone()
    run(tmp_path, fake, bluetooth_on=True)
    assert fake.requests[0].endswith("adapter.action.REQUEST_DISCOVERABLE;end")
    other = phone()
    other_run = tmp_path / "off"
    other_run.mkdir()
    run(other_run, other, bluetooth_on=None)
    assert other.requests[0].endswith("adapter.action.REQUEST_ENABLE;end")


def test_a_dialog_that_takes_reads_to_show_is_read_again_up_to_ten_times(tmp_path):
    fake = phone(dialog_lag=3)
    _, lines = run(tmp_path, fake)
    shown = checks(lines, "screen_read")[-1]
    assert (shown["screen"], shown["dialog"], shown["reads"]) == ("dialog", True, 4)
    assert fake.dumps[-1] == "x-dialog"


def test_a_dialog_that_never_shows_writes_dialog_not_shown_and_the_journey_goes_on(tmp_path):
    fake = phone(has_bluetooth=False)
    code, lines = run(tmp_path, fake)
    assert code == 0
    missing = checks(lines, "dialog_not_shown")
    assert len(missing) == 1 and missing[0]["reads"] == 10 and missing[0]["dialog"] is False
    assert fake.dumps == ["x-launcher", "x-settings"]
    assert [line["screen"] for line in checks(lines, "warm_snapshot")] == ["launcher", "settings"]
    assert len(fake.inputs) == 9


def test_a_settings_that_never_opens_is_not_surveyed_and_is_not_the_launcher(tmp_path):
    def stuck(phone, words):
        return phone.screen if words[0] == "open-url" else react(phone, words)

    fake = phone(react=stuck)
    code, lines = run(tmp_path, fake)
    assert code == 0 and len(checks(lines, "settings_not_shown")) == 1
    assert fake.dumps == ["x-launcher"]


def test_a_focus_that_never_agrees_is_kept_as_a_finding_and_the_screen_is_still_surveyed(tmp_path):
    fake = phone(focus=lambda p: "com.other" if p.screen == "launcher" else p.current.app)
    _, lines = run(tmp_path, fake)
    launcher = checks(lines, "screen_read")[0]
    assert (launcher["screen"], launcher["agrees"], launcher["focus_app"], launcher["reads"]) == (
        "launcher",
        False,
        "com.other",
        3,
    )
    assert "x-launcher" in fake.dumps


def test_a_focus_that_agrees_on_the_second_read_stops_the_reading(tmp_path):
    seen = []

    def focus(p):
        seen.append(p.screen)
        return "com.other" if len(seen) == 1 else p.current.app

    fake = phone(focus=focus)
    _, lines = run(tmp_path, fake)
    launcher = checks(lines, "screen_read")[0]
    assert (launcher["agrees"], launcher["reads"]) == (True, 2)


def test_a_phone_with_no_focus_line_has_no_agreement_to_check(tmp_path):
    _, lines = run(tmp_path, phone(focus=lambda p: None))
    assert [line["agrees"] for line in checks(lines, "screen_read")] == [None] * 3


def test_a_scroll_that_the_screen_refuses_is_a_line_with_its_error_and_no_delivery(tmp_path):
    def flat(phone, words):
        if words[0] == "scroll":
            raise FakePhone.Refused("NOT_FOUND")
        return react(phone, words)

    _, lines = run(tmp_path, phone(react=flat))
    down, up = [s for s in checks(lines, "input") if s["name"].startswith("scroll")]
    assert (down["error"], down["delivery"], down["changed"]) == ("NOT_FOUND", "not_delivered", False)
    assert (up["error"], up["changed"]) == ("NOT_FOUND", False)


def test_no_read_that_works_aborts_before_any_input(tmp_path):
    fake = phone(snapshot_failures=99)
    code, lines = run(tmp_path, fake)
    assert code == 1 and fake.inputs == []
    assert [line["check"] for line in lines] == ["aborted"] and lines[0]["sent"] == []


def test_a_survey_stops_at_the_input_after_which_nothing_can_be_read(tmp_path):
    class Dies(Phone):
        def observe(self, command, words):
            if len(self.inputs) >= 2:
                return refusal_of(self)
            return super().observe(command, words)

    def refusal_of(fake):
        from port_support import refusal

        return refusal("snapshot", fake.serial, "NO_SURFACE")

    fake = Dies(serial="S1", screens=dict(SCREENS), screen="launcher", react=react)
    fake.requests = []
    code, lines = run(tmp_path, fake)
    assert code == 1 and lines[-1]["check"] == "aborted" and len(lines[-1]["sent"]) == 2
    assert len(fake.inputs) == 2


@pytest.mark.parametrize(
    ("facts", "message"),
    [({"serial": "OTHER"}, "facts.json is for OTHER"), ({"awake": False}, "the screen is off")],
)
def test_the_survey_refuses_facts_of_another_phone_and_a_sleeping_screen(tmp_path, facts, message):
    fake = phone()
    with pytest.raises(SystemExit, match=message):
        run(tmp_path, fake, **facts)
    assert fake.commands == []


def test_the_survey_needs_the_facts_first(tmp_path):
    with pytest.raises(SystemExit, match="Run facts.py first"):
        survey.main([str(tmp_path), "S1", "x"], phone().runner)


def call(ms, size, app="a", dialog=False, ok=True, settled="settled", lines=3):
    data = {"app": app, "dialog": dialog, "settled": settled, "tree": ["x"] * lines}
    return calls.Call({"ms": ms, "stdout_bytes": size, "stdout": {"ok": ok, "data": data}})


def test_a_summary_counts_errors_and_wrong_screens_and_gives_median_range_and_bytes():
    expected = survey.Seen(call(0, 0, "a"))
    got = survey.summarize(
        [call(200, 800), call(210, 900), call(260, 8192), call(220, 700, app="b"), call(300, 100, ok=False)],
        expected,
    )
    assert got == {
        "runs": 5,
        "errors": 1,
        "wrong_screen": 1,
        "median_ms": 220,
        "range_ms": [200, 300],
        "bytes": [100, 8192],
        "under_8_kb": False,
        "tree_lines": [3, 3],
    }
