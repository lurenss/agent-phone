"""card.py turns a run's files into docs/devices/<name>.md and a row of docs/devices/README.md. The
status rules are tested on lines written the way survey.py writes them, and the whole chain is run
once on fake phones, so card.py reads what the other scripts really write."""

import copy
import json

import pytest
from port_support import FakePhone, script
from support import ROOT, fixture_xml
from test_port_survey import phone as survey_phone
from test_port_sweep import APPS
from test_port_sweep import SCREENS as SWEEP_SCREENS
from test_port_sweep import react as sweep_react

card = script("card")
status = script("card_status")
facts_script = script("facts")
survey_script = script("survey")
sweep_script = script("sweep")
fixtures_script = script("fixtures")
Status = status.Status

FACTS = {
    "serial": "S1",
    "manufacturer": "samsung",
    "brand": "samsung",
    "model": "SM-J730F",
    "device": "j7y17lte",
    "release": "9",
    "api": 28,
    "abi": "armeabi-v7a",
    "locale": "en-US",
    "language": "en",
    "policy_languages": ["en", "it"],
    "language_covered": True,
    "emulator": False,
    "displays": [{"id": 0, "width": 1080, "height": 1920, "state": "ON"}],
    "top_focused_display": 0,
    "awake": True,
    "bluetooth_on": False,
    "ime": "com.sec.android.inputmethod",
    "hints": [],
}
STEPS = [
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


def survey_lines() -> list[dict]:
    lines = []
    for screen, app, dialog in (
        ("launcher", "a.home", False),
        ("settings", "a.prefs", False),
        ("dialog", "a.prefs", True),
    ):
        lines.append(
            {"check": "screen_read", "screen": screen, "app": app, "window": "application", "dialog": dialog}
            | {"settled": "settled", "lines": 3, "focus_app": app, "agrees": True, "reads": 1}
        )
        lines.append({"check": "raw_dump", "screen": screen, "file": f"x-{screen}", "ok": True})
        lines.append(
            {"check": "warm_snapshot", "screen": screen, "runs": 20, "errors": 0, "wrong_screen": 0}
            | {
                "median_ms": 210,
                "range_ms": [200, 260],
                "bytes": [800, 900],
                "under_8_kb": True,
                "tree_lines": [3, 3],
            }
        )
        lines.append({"check": "warm_settle", "screen": screen, "settled": 10, "runs": 10, "median_ms": 290})
    for number, name in enumerate(STEPS, 1):
        argv = (
            ["scroll", name.split()[1]]
            if name.startswith("scroll")
            else ["press", "back" if "back" in name else "home"]
        )
        lines.append(
            {"check": "input", "step": number, "name": name, "argv": argv, "delivery": "delivered_unverified"}
            | {
                "verified_by": None,
                "error": None,
                "after_app": "a.prefs",
                "after_dialog": False,
                "changed": True,
            }
        )
    lines.append({"check": "inputs", "sent": ["agent-phone -d S1 press home"] * 9})
    return lines


def evidence(facts=None, survey=None, fixtures=None, apps=()):
    return status.Evidence(
        facts or copy.deepcopy(FACTS), tuple(survey or survey_lines()), fixtures, tuple(apps)
    )


def edited(check, screen=None, **changes):
    lines = survey_lines()
    for line in lines:
        if line["check"] == check and screen in (None, line.get("screen"), line.get("name")):
            line.update(changes)
    return lines


def test_a_clean_run_works_with_no_reason():
    assert status.status_of(evidence()) == (Status.WORKS, [])
    assert status.done_when_4(evidence()) == []


@pytest.mark.parametrize(
    ("survey", "reason"),
    [
        (
            survey_lines() + [{"check": "aborted", "reason": "no read of the screen worked", "sent": []}],
            "The survey stopped",
        ),
        (
            survey_lines() + [{"check": "launcher_not_shown", "reads": 3, "app": None}],
            "launcher was never read",
        ),
        (edited("warm_snapshot", "settings", errors=20), "Every snapshot of the settings failed"),
        (edited("input", "home", error="TRANSPORT"), "The key press 'home' failed with TRANSPORT"),
        (
            edited("input", "back from about", error="ACTION_FAILED"),
            "'back from about' failed with ACTION_FAILED",
        ),
    ],
)
def test_a_phone_agent_phone_cannot_read_or_drive_is_blocked_and_the_card_says_why(survey, reason):
    got, reasons = status.status_of(evidence(survey=survey))
    assert got is Status.BLOCKED and any(reason in r for r in reasons)


@pytest.mark.parametrize(
    ("survey", "reason"),
    [
        (edited("warm_snapshot", "settings", median_ms=400), "median snapshot of the settings took 400 ms"),
        (edited("warm_snapshot", "dialog", bytes=[800, 8192]), "A snapshot of the dialog was 8192 bytes"),
        (edited("warm_snapshot", "dialog", errors=1), "1 of 20 snapshots of the dialog failed"),
        (
            edited("warm_snapshot", "settings", wrong_screen=2),
            "2 snapshots of the settings showed another screen",
        ),
        (edited("warm_settle", "settings", settled=9), "9 of 10 settled snapshots of the settings settled"),
        (
            survey_lines() + [{"check": "dialog_not_shown", "reads": 10, "app": "a.prefs", "dialog": False}],
            "dialog was never shown",
        ),
        (
            survey_lines() + [{"check": "settings_not_shown", "reads": 3, "app": "a.home", "dialog": False}],
            "settings was never shown",
        ),
        (
            edited("input", "open about", error="NOT_FOUND", delivery="not_delivered"),
            "'open about' failed with NOT_FOUND",
        ),
        (edited("input", "back from about", changed=False), "'back from about' changed no screen"),
        (edited("input", "scroll down", changed=False), "'scroll down' moved nothing"),
        (edited("input", "scroll up", error="NOT_FOUND"), "'scroll up' failed with NOT_FOUND"),
        (
            edited("screen_read", "launcher", agrees=False, focus_app="b.other"),
            "settled read named a.home and the focus named b.other",
        ),
    ],
)
def test_a_phone_that_works_with_a_failed_check_is_works_with_limits_and_names_the_check(survey, reason):
    got, reasons = status.status_of(evidence(survey=survey))
    assert got is Status.LIMITS and any(reason in r for r in reasons), reasons


def test_the_median_and_the_byte_budget_pass_one_below_the_limit():
    ok = edited("warm_snapshot", "settings", median_ms=399, bytes=[1, 8191])
    assert status.status_of(evidence(survey=ok))[0] is Status.WORKS


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"language_covered": False, "language": "ar"}, "no rules for the language ar"),
        (
            {"displays": FACTS["displays"] + [{"id": 4, "width": 1080, "height": 1240, "state": "ON"}]},
            "more than one display",
        ),
        ({"top_focused_display": 4}, "Keys go to display 4"),
    ],
)
def test_a_language_a_second_display_and_keys_on_another_display_are_limits(changes, reason):
    got, reasons = status.status_of(evidence(facts=FACTS | changes))
    assert got is Status.LIMITS and any(reason in r for r in reasons)


def test_a_fixture_anomaly_is_a_limit_and_a_missing_fixture_step_is_not():
    anomaly = {
        "screens": {},
        "missing": [],
        "anomalies": [{"screen": "launcher", "rule": "no_dialog", "detail": "x"}],
    }
    got, reasons = status.status_of(evidence(fixtures=anomaly))
    assert got is Status.LIMITS and "launcher fixture is an anomaly (no_dialog)" in reasons[0]
    assert status.status_of(evidence(fixtures=None))[0] is Status.WORKS


def test_a_blocked_phone_lists_its_blockers_before_its_limits():
    survey = edited("input", "home", error="TRANSPORT")
    survey = [line | ({"median_ms": 900} if line["check"] == "warm_snapshot" else {}) for line in survey]
    got, reasons = status.status_of(evidence(survey=survey))
    assert got is Status.BLOCKED and reasons[0].startswith("The key press")
    assert any("median snapshot" in r for r in reasons[1:])


def test_a_sweep_never_changes_the_status():
    apps = [{"package": "a.b", "launched": False, "launch_error": "NOT_FOUND"}]
    assert status.status_of(evidence(apps=apps))[0] is Status.WORKS


def written(tmp_path, ev, name="demo", notes=""):
    run = tmp_path / "20261101T000000Z-demo-port"
    run.mkdir(exist_ok=True)
    (run / "facts.json").write_text(json.dumps(ev.facts))
    (run / "survey.jsonl").write_text("".join(json.dumps(line) + "\n" for line in ev.survey))
    if ev.fixtures is not None:
        (run / "fixtures.json").write_text(json.dumps(ev.fixtures))
    if ev.apps:
        (run / "apps.jsonl").write_text("".join(json.dumps(line) + "\n" for line in ev.apps))
    docs = tmp_path / "docs"
    assert card.main([str(run), name], docs) == 0
    return docs


def test_the_card_has_the_sections_in_order_and_ends_with_an_empty_notes_section(tmp_path):
    text = (written(tmp_path, evidence()) / "demo.md").read_text()
    headings = [line for line in text.splitlines() if line.startswith("## ")]
    assert headings == [
        "## Device facts",
        "## Done-when 4",
        "## Input journey",
        "## Screen reads and anomalies",
        "## Apps",
        "## Hints",
        "## Fixes and notes",
    ]
    assert text.startswith("# samsung SM-J730F (demo)\n\n**Status: works.**")
    assert text.endswith("## Fixes and notes\n")
    assert "No sweep was run." in text and "No fixtures were made." in text
    assert "20261101T000000Z-demo-port" in text and "Done-when 4 is met" in text


def test_the_card_shows_the_facts_the_checks_and_the_journey(tmp_path):
    text = (written(tmp_path, evidence()) / "demo.md").read_text()
    assert "| Android | 9 (API 28) |" in text and "| Displays | 0: 1080x1920 ON |" in text
    assert (
        "| settings | a.prefs | 20 | 0 | 0 | 210 | 200 to 260 | 800 to 900 | yes | 10 of 10 | 290 |" in text
    )
    assert "| 6 | scroll down | delivered_unverified | - | - | a.prefs | yes |" in text
    assert "9 inputs were sent. None was a tap." in text
    assert "| launcher | a.home | application | no | settled | a.home | yes | 1 |" in text


def test_a_failed_check_is_on_the_card_with_its_reason_and_the_hints_are_listed(tmp_path):
    ev = evidence(
        facts=FACTS | {"hints": ["Only display 0 is read and tapped (A6-1)."], "top_focused_display": 4},
        survey=edited("warm_snapshot", "settings", median_ms=555),
    )
    text = (written(tmp_path, ev) / "demo.md").read_text()
    assert "**Status: works with limits.**" in text
    assert "- The median snapshot of the settings took 555 ms, not under 400." in text
    assert "Done-when 4 is not met:" in text
    assert "- Only display 0 is read and tapped (A6-1)." in text


def test_what_stands_under_fixes_and_notes_survives_a_new_run(tmp_path):
    docs = written(tmp_path, evidence())
    notes = "\n### Xiaomi\n\nTurned on USB debugging (Security settings).\n\n- tap refused once\n"
    path = docs / "demo.md"
    path.write_text(path.read_text() + notes)
    ev = evidence(facts=FACTS | {"model": "SM-J999"})
    again = written(tmp_path, ev)
    text = (again / "demo.md").read_text()
    assert text.endswith("## Fixes and notes\n" + notes) and "SM-J999" in text
    assert written(tmp_path, ev).joinpath("demo.md").read_text() == text


def test_a_card_that_lost_its_notes_heading_gets_an_empty_one(tmp_path):
    docs = written(tmp_path, evidence())
    (docs / "demo.md").write_text("# something else\n")
    assert written(tmp_path, evidence()).joinpath("demo.md").read_text().endswith("## Fixes and notes\n")


def test_the_index_is_created_with_its_columns_and_one_row_for_the_device(tmp_path):
    index = (written(tmp_path, evidence()) / "README.md").read_text()
    assert "| name | model | Android | language | status | card |" in index
    assert "| demo | samsung SM-J730F | 9 (API 28) | en-US | works | [demo.md](demo.md) |" in index
    assert "`works with limits`" in index and "`blocked`" in index
    assert index.count("| demo |") == 1 and index.endswith("\n")


def test_a_second_device_adds_a_row_and_a_rerun_replaces_its_own_and_keeps_the_text_around(tmp_path):
    docs = written(tmp_path, evidence(), "demo")
    path = docs / "README.md"
    path.write_text(path.read_text().replace("# Device cards", "# Device cards, edited by hand"))
    blocked = evidence(facts=FACTS | {"model": "Other", "locale": "ar-EG", "language_covered": False})
    written(tmp_path, blocked, "other")
    rows = [line for line in path.read_text().splitlines() if line.startswith("| ") and "---" not in line]
    assert [r.split("|")[1].strip() for r in rows] == ["name", "demo", "other"]
    other = "| other | samsung Other | 9 (API 28) | ar-EG (not covered) | works with limits | [other.md](other.md) |"  # noqa: E501
    assert other in rows
    again = evidence(survey=edited("input", "home", error="TRANSPORT"))
    written(tmp_path, again, "demo")
    text = path.read_text()
    rows = [line for line in text.splitlines() if line.startswith("| ") and "---" not in line]
    assert [r.split("|")[1].strip() for r in rows] == ["name", "demo", "other"]
    assert "| demo | samsung SM-J730F | 9 (API 28) | en-US | blocked | [demo.md](demo.md) |" in rows
    assert text.startswith("# Device cards, edited by hand")


def test_an_index_with_text_after_the_table_keeps_it_and_one_with_no_table_gets_one():
    row = "| a | b | c | d | works | [a.md](a.md) |"
    existing = card.update_index(None, "x", "| x | b | c | d | works | [x.md](x.md) |") + "\nMore text.\n"
    text = card.update_index(existing, "a", row)
    assert text.index(row) < text.index("More text.") and text.endswith("More text.\n")
    plain = card.update_index("# Notes\n", "a", row)
    assert plain.startswith("# Notes\n") and "| name | model |" in plain and row in plain


def test_a_sample_label_is_on_the_card_only_when_it_is_a_known_ui_label(tmp_path):
    apps = [
        {
            "package": "a.b",
            "launched": True,
            "settled_ms": 900,
            "snapshot_lines": 12,
            "targets": 4,
            "clear": 1,
        }
        | {
            "commits": {"social": 2},
            "denied": 0,
            "refused": 0,
            "samples": {"social": ["Follow", "Marco Rossi"]},
        },
        {"package": "c.d", "launched": False, "launch_error": "NOT_FOUND"},
        {"package": "g.h", "launched": True, "snapshot_lines": 0, "targets": 0, "clear": 0, "commits": {}}
        | {"denied": 0, "refused": 0, "wait_error": "TIMEOUT", "settled_ms": None},
        {"package": "e.f", "launched": False, "skipped": "evidence: the input names the protected package"},
    ]
    text = (written(tmp_path, evidence(apps=apps)) / "demo.md").read_text()
    assert "| a.b | yes | 900 | 12 | 4 | 1 | social 2 | 0 | 0 | - |" in text
    assert "- a.b: social: `Follow`; 1 not shown" in text and "Marco Rossi" not in text
    assert "| c.d | no | - | - | - | - | - | - | - | NOT_FOUND |" in text
    assert "| g.h | yes | - | 0 | 0 | 0 | - | 0 | 0 | wait TIMEOUT |" in text


def test_a_pipe_in_a_fact_does_not_break_the_table(tmp_path):
    text = (written(tmp_path, evidence(facts=FACTS | {"ime": "a|b"})) / "demo.md").read_text()
    assert "| Keyboard | a/b |" in text


def test_a_run_with_no_facts_or_no_survey_is_refused_with_the_next_step(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    with pytest.raises(SystemExit, match="Run facts.py and survey.py first"):
        card.main([str(run), "demo"], tmp_path / "docs")
    assert not (tmp_path / "docs" / "README.md").exists()


THOR_PROPS = """[persist.sys.locale]: [it_VA]
[ro.build.version.release]: [13]
[ro.build.version.sdk]: [33]
[ro.product.brand]: [AYN]
[ro.product.cpu.abi]: [arm64-v8a]
[ro.product.device]: [kalama]
[ro.product.manufacturer]: [AYN]
[ro.product.model]: [Thor]
"""
RAW = {"launcher": "thor-launcher", "settings": "settings-home", "dialog": "dialog-over-app"}


def test_the_whole_chain_runs_on_fake_phones_and_the_card_reads_what_each_script_wrote(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_PHONE_HOME", str(tmp_path / "state"))
    run, raw = tmp_path / "run", tmp_path / "raw"
    run.mkdir()
    raw.mkdir()
    phone = survey_phone(raw_dir=raw, raw_xml=lambda p: fixture_xml(RAW.get(p.screen, "settings-home")))
    phone.shell = {
        "getprop": THOR_PROPS,
        "dumpsys display": (ROOT / "tests" / "fixtures" / "adb" / "dumpsys-display-thor.txt").read_text(),
        "dumpsys window displays": phone.window_dump(),
        "dumpsys power": "mWakefulness=Awake\n",
        "settings get global bluetooth_on": "0\n",
        "settings get secure default_input_method": "com.google.android.inputmethod.latin/.LatinIME\n",
    }
    assert facts_script.main([str(run), "S1"], phone.runner) == 0
    assert survey_script.main([str(run), "S1", "demo"], phone.runner) == 0
    paths = fixtures_script.Paths(raw, tmp_path / "fixtures", tmp_path / "tests")
    assert fixtures_script.main([str(run), "demo"], paths) == 0
    shop = FakePhone(serial="S1", screens=dict(SWEEP_SCREENS), screen="home", react=sweep_react)
    shop.raw_dir, shop.raw_xml = raw, lambda p: APPS.get(p.screen, APPS["chat.app"])
    assert sweep_script.main([str(run), "S1", "shop.app", "game.app"], shop.runner, raw) == 0
    docs = tmp_path / "docs"
    assert card.main([str(run), "demo"], docs) == 0
    text = (docs / "demo.md").read_text()
    assert text.startswith("# AYN Thor (demo)\n\n**Status: works with limits.**")
    assert "The phone has more than one display" in text
    assert "| launcher | com.vendor.home |" in text and "| settings | com.vendor.prefs |" in text
    assert "| dialog | com.vendor.prefs | application | yes | settled |" in text
    assert "| shop.app | yes |" in text and "| game.app | yes |" in text
    assert "No anomaly." in text and "9 inputs were sent. None was a tap." in text
    assert "| Locale | it-VA, language it, covered by the policy |" in text
    index = (docs / "README.md").read_text()
    assert "| demo | AYN Thor | 13 (API 33) | it-VA | works with limits | [demo.md](demo.md) |" in index


def test_a_screen_with_no_raw_dump_is_a_line_on_the_card(tmp_path):
    fixtures = {"screens": {}, "missing": ["dialog"], "anomalies": []}
    text = (written(tmp_path, evidence(fixtures=fixtures)) / "demo.md").read_text()
    assert "- No fixture of the dialog: no raw dump was saved." in text
