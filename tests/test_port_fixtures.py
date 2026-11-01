"""fixtures.py redacts a survey's raw dumps and reads each as agent-phone will. The raw dumps here are
the repo's own redacted fixtures, which are real dumps of the J7 and the Thor, so every expected value
comes from what FINDINGS says those screens are (A6-1, A6-3)."""

import json
import subprocess
import sys

import pytest
from port_support import script
from support import ROOT, dump, fixture_xml, node
from test_fixtures_are_redacted import unredacted_values

from agent_phone.core.geometry import Size

fixtures = script("fixtures")
Screen = fixtures.Screen
Rule = fixtures.Rule
NATURAL = Size(1080, 1920)


def paths(tmp_path):
    return fixtures.Paths(tmp_path / "raw", tmp_path / "fixtures", tmp_path / "tests")


def stage(tmp_path, **raw: str) -> tuple:
    """Raw dumps named `launcher`, `settings` or `dialog`, from the text given, for the name `demo`."""
    where = paths(tmp_path)
    where.raw.mkdir(parents=True)
    where.tests.mkdir()
    for screen, xml in raw.items():
        (where.raw / f"demo-{screen}.raw.xml").write_text(xml)
    run = tmp_path / "run"
    run.mkdir()
    facts = {"displays": [{"id": 0, "width": 1080, "height": 1920, "state": "ON"}]}
    (run / "facts.json").write_text(json.dumps(facts))
    return where, run


GOOD = {
    "launcher": fixture_xml("thor-launcher"),
    "settings": fixture_xml("settings-home"),
    "dialog": fixture_xml("dialog-over-app"),
}


def reading(xml: str):
    return fixtures.read_dump(xml, NATURAL)


def rules(screen, xml: str) -> list:
    return [a.rule for a in fixtures.anomalies(screen, reading(xml))]


def test_the_thor_launcher_reads_with_its_other_display_as_information_and_no_anomaly():
    got = reading(GOOD["launcher"])
    assert [(w.package, w.kind, w.active) for w in got.windows] == [
        ("com.android.systemui", "system", False),
        ("com.android.launcher3", "application", True),
    ]
    assert got.windows[1].bounds == (0, 0, 1920, 1079)
    assert (got.other_display_roots, got.rotation, got.display) == (1, 1, (1920, 1080))
    assert (got.active, got.dialog, got.others) == ("com.android.launcher3", False, ("com.android.systemui",))
    assert rules(Screen.LAUNCHER, GOOD["launcher"]) == []


def test_a_dialog_over_an_app_reads_dialog_true_and_is_no_anomaly_on_the_dialog_screen():
    got = reading(GOOD["dialog"])
    assert (got.active, got.dialog, got.rotation, got.display) == (
        "com.android.settings",
        True,
        0,
        (1080, 1920),
    )
    assert rules(Screen.DIALOG, GOOD["dialog"]) == []


def test_a_full_screen_app_that_reads_dialog_true_is_an_anomaly_and_a_dialog_that_reads_false_is_one():
    assert rules(Screen.LAUNCHER, GOOD["dialog"]) == [Rule.DIALOG_ON_FULL_SCREEN]
    assert rules(Screen.SETTINGS, GOOD["dialog"]) == [Rule.DIALOG_ON_FULL_SCREEN]
    assert rules(Screen.DIALOG, fixture_xml("ig-feed")) == [Rule.NO_DIALOG]


def window(package, bounds, **attrs):
    return node("android.widget.FrameLayout", package=package, bounds=bounds, **attrs)


def test_a_system_window_that_is_active_while_an_application_window_exists_is_an_anomaly():
    xml = dump(
        window("com.android.systemui", "[0,0][1080,1920]"), window("com.vendor.app", "[0,0][1080,1920]")
    )
    assert rules(Screen.SETTINGS, xml) == [Rule.SYSTEM_WINDOW_ACTIVE]
    shade = fixture_xml("notification-shade")
    assert rules(Screen.SETTINGS, shade) == [], "the shade alone is no application beneath it"


def test_a_window_may_stop_2_px_short_of_the_display_and_reach_2_px_past_it_but_no_more():
    def with_bounds(bounds):
        return dump(window("com.vendor.app", bounds))

    assert rules(Screen.SETTINGS, with_bounds("[-2,-2][1082,1922]")) == []
    for outside in ("[-3,0][1080,1920]", "[0,-3][1080,1920]", "[0,0][1083,1920]", "[0,0][1080,1923]"):
        assert rules(Screen.SETTINGS, with_bounds(outside)) == [Rule.OUT_OF_BOUNDS], outside


def test_a_dump_with_no_window_that_can_hold_focus_is_an_anomaly():
    strip_only = dump(window("com.android.systemui", "[0,0][1080,63]"))
    got = reading(strip_only)
    assert (got.active, got.dialog) == (None, None) and got.error is None
    assert rules(Screen.LAUNCHER, strip_only) == [Rule.NO_ACTIVE_WINDOW]
    other_display = dump(window("com.vendor.app", "[0,0][1080,1920]", display_id=4))
    assert reading(other_display).error and rules(Screen.LAUNCHER, other_display) == [Rule.NO_ACTIVE_WINDOW]
    assert rules(Screen.LAUNCHER, "<hierarchy") == [Rule.NO_ACTIVE_WINDOW]


def test_the_table_the_run_prints_names_each_screen_and_what_was_flagged():
    found = [fixtures.Anomaly("launcher", Rule.DIALOG_ON_FULL_SCREEN, "x")]
    readings = {Screen.LAUNCHER: reading(GOOD["dialog"]), Screen.DIALOG: reading(GOOD["dialog"])}
    lines = fixtures.table(readings, found)
    assert lines[0].split()[:2] == ["screen", "active"] and lines[0].endswith("anomalies")
    assert lines[1].split()[0] == "launcher" and lines[1].endswith("dialog_on_full_screen")
    assert lines[2].split()[0] == "dialog" and lines[2].endswith(" -")


def test_a_clean_survey_writes_redacted_fixtures_fixtures_json_and_no_test_without_the_flag(tmp_path, capsys):
    private = GOOD["settings"].replace('text=""', 'text="Lorenzo Padoan"', 1)
    where, run = stage(tmp_path, launcher=GOOD["launcher"], settings=private, dialog=GOOD["dialog"])
    assert fixtures.main([str(run), "demo"], where) == 0
    names = sorted(p.name for p in where.fixtures.iterdir())
    assert names == ["demo-dialog.xml", "demo-launcher.xml", "demo-settings.xml"]
    texts = {p.name: p.read_text() for p in where.fixtures.iterdir()}
    assert "Lorenzo Padoan" not in texts["demo-settings.xml"] and "redacted-1" in texts["demo-settings.xml"]
    assert all(unredacted_values(text) == [] for text in texts.values())
    document = json.loads((run / "fixtures.json").read_text())
    assert list(document["screens"]) == ["launcher", "settings", "dialog"]
    launcher = document["screens"]["launcher"]
    assert (
        launcher["other_display_roots"] == 1
        and launcher["rotation"] == 1
        and launcher["display"] == [1920, 1080]
    )
    assert launcher["active"] == "com.android.launcher3" and launcher["dialog"] is False
    assert launcher["windows"][1] == {
        "package": "com.android.launcher3",
        "kind": "application",
        "bounds": [0, 0, 1920, 1079],
        "active": True,
    }
    assert document["screens"]["dialog"]["dialog"] is True
    assert document["anomalies"] == [] and document["missing"] == []
    assert list(where.tests.iterdir()) == []
    assert "launcher" in capsys.readouterr().out


def test_an_anomaly_exits_1_names_itself_and_writes_no_test_even_when_asked(tmp_path, capsys):
    where, run = stage(tmp_path, launcher=GOOD["dialog"], settings=GOOD["settings"], dialog=GOOD["dialog"])
    assert fixtures.main([str(run), "demo", "--write-test"], where) == 1
    out = capsys.readouterr().out
    assert "anomaly launcher: dialog_on_full_screen" in out and "no test written" in out
    assert list(where.tests.iterdir()) == []
    document = json.loads((run / "fixtures.json").read_text())
    assert [a["rule"] for a in document["anomalies"]] == ["dialog_on_full_screen"]


def test_a_screen_with_no_raw_dump_is_a_note_and_not_an_anomaly(tmp_path, capsys):
    where, run = stage(tmp_path, launcher=GOOD["launcher"], settings=GOOD["settings"])
    assert fixtures.main([str(run), "demo", "--write-test"], where) == 0
    assert "note: no raw dump of the dialog" in capsys.readouterr().out
    assert json.loads((run / "fixtures.json").read_text())["missing"] == ["dialog"]
    assert "demo-dialog" not in (where.tests / "test_demo_dumps.py").read_text()


def test_no_raw_dump_at_all_and_no_facts_are_errors_with_a_next_step(tmp_path):
    where, run = stage(tmp_path)
    with pytest.raises(SystemExit, match="Run survey.py first"):
        fixtures.main([str(run), "demo"], where)
    (run / "facts.json").unlink()
    with pytest.raises(SystemExit, match="Run facts.py first"):
        fixtures.main([str(run), "demo"], where)
    (run / "facts.json").write_text(json.dumps({"displays": []}))
    with pytest.raises(SystemExit, match="no display 0"):
        fixtures.main([str(run), "demo"], where)


def test_a_dump_that_is_not_xml_is_an_error_and_leaves_no_fixture(tmp_path):
    where, run = stage(tmp_path, launcher="<hierarchy")
    with pytest.raises(SystemExit, match="redact.py failed"):
        fixtures.main([str(run), "demo"], where)


def test_the_written_test_is_formatted_and_lints_under_the_repos_rules(tmp_path):
    source = fixtures.render_test(
        "demo-two",
        NATURAL,
        [
            ("demo-two-launcher", "com.android.launcher3", False, ("com.android.systemui",)),
            ("demo-two-dialog", "a.b", True, ()),
        ],
    )
    config = ["--config", str(ROOT / "pyproject.toml"), "--stdin-filename", "tests/test_demo_two_dumps.py"]
    for command in (["ruff", "check", *config, "-"], ["ruff", "format", "--check", *config, "-"]):
        done = subprocess.run(command, input=source, capture_output=True, text=True, cwd=ROOT)
        assert done.returncode == 0, done.stdout + done.stderr


def run_generated(tmp_path, test_source: str) -> subprocess.CompletedProcess:
    """The generated test, in a folder of its own with a `support` that reads the generated fixtures."""
    home = tmp_path / "pytest-home"
    home.mkdir(exist_ok=True)
    (home / "support.py").write_text(
        "from pathlib import Path\n\n\ndef fixture_xml(name):\n"
        f"    return (Path({str(tmp_path / 'fixtures')!r}) / f'{{name}}.xml').read_text()\n"
    )
    (home / "test_demo_dumps.py").write_text(test_source)
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--rootdir", str(home), str(home)],
        capture_output=True,
        text=True,
        cwd=home,
    )


def test_the_written_test_passes_on_the_fixtures_it_pins_and_fails_when_a_pin_is_wrong(tmp_path):
    where, run = stage(tmp_path, **GOOD)
    assert fixtures.main([str(run), "demo", "--write-test"], where) == 0
    source = (where.tests / "test_demo_dumps.py").read_text()
    assert '("demo-dialog", "com.android.settings", True, ("com.android.systemui",)),' in source
    assert "NATURAL = Size(1080, 1920)" in source
    done = run_generated(tmp_path, source)
    assert done.returncode == 0 and "3 passed" in done.stdout, done.stdout + done.stderr
    wrong = source.replace('"com.android.settings", True,', '"com.android.settings", False,')
    broken = run_generated(tmp_path, wrong)
    assert broken.returncode == 1 and "1 failed" in broken.stdout
