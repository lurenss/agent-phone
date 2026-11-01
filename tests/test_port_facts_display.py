"""Which display gets key input. Android 13 prints `mTopFocusedDisplayId` in `dumpsys window`. Android 15
prints it in neither `dumpsys window` nor `dumpsys window displays`, so facts.py reads the dump that has
it, and without one line it infers display 0 only on a phone with one display."""

import json
from dataclasses import asdict

from port_support import script
from test_port_card import FACTS
from test_port_facts import J7_DISPLAY, J7_PROPS, J7_WINDOW, THOR_DISPLAY, THOR_WINDOW, facts_of, phone

facts = script("facts")
card = script("card")

THOR_WITHOUT_THE_LINE = THOR_WINDOW.replace("  mTopFocusedDisplayId=0\n", "")
PLAIN_DUMPSYS_WINDOW = (
    "WINDOW MANAGER POLICY STATE (dumpsys window policy)\n  mHasPermanentDpad=false\n"
    "  mTopFocusedDisplayId=0\n"
)
PLAIN_WITHOUT_THE_LINE = PLAIN_DUMPSYS_WINDOW.replace("  mTopFocusedDisplayId=0\n", "")
UNKNOWN = "Unknown which display gets key input."


def facts_json(tmp_path, window, plain="", display=THOR_DISPLAY) -> dict:
    fake = phone()
    fake.shell |= {
        "getprop": J7_PROPS,
        "dumpsys display": display,
        "dumpsys window displays": window,
        "dumpsys window": plain,
    }
    assert facts.main([str(tmp_path), "S1"], fake.runner) == 0
    return json.loads((tmp_path / "facts.json").read_text())


def test_a_phone_with_one_display_and_no_line_gets_display_0_marked_as_inferred(tmp_path):
    got = asdict(facts_of(display=J7_DISPLAY, window=J7_WINDOW))
    assert (got["top_focused_display"], got.get("top_focused_display_inferred")) == (0, True)
    assert got["hints"] == ()


def test_the_inference_is_in_facts_json_and_in_what_the_script_prints(tmp_path, capsys):
    document = facts_json(tmp_path, J7_WINDOW, PLAIN_WITHOUT_THE_LINE, J7_DISPLAY)
    assert (document["top_focused_display"], document.get("top_focused_display_inferred")) == (0, True)
    assert "keys go to display 0 (inferred)" in capsys.readouterr().out


def test_a_line_that_names_the_display_is_not_inferred(tmp_path):
    assert (
        asdict(facts_of(display=J7_DISPLAY, window=J7_WINDOW + "  mTopFocusedDisplayId=0\n"))[
            "top_focused_display"
        ]
        == 0
    )
    document = facts_json(tmp_path, THOR_WINDOW)
    assert document["top_focused_display"] == 0
    assert document.get("top_focused_display_inferred") is not True


def test_several_displays_and_no_line_is_unknown_and_says_so(tmp_path, capsys):
    got = asdict(facts_of(display=THOR_DISPLAY, window=THOR_WITHOUT_THE_LINE))
    assert UNKNOWN in got["hints"]
    assert got["top_focused_display"] is None and got.get("top_focused_display_inferred") is False
    document = facts_json(tmp_path, THOR_WITHOUT_THE_LINE, PLAIN_WITHOUT_THE_LINE)
    assert document["top_focused_display"] is None and UNKNOWN in document["hints"]
    assert "keys go to an unknown display" in capsys.readouterr().out


def test_no_display_read_and_no_line_is_unknown_and_has_no_hint():
    got = asdict(facts_of(window=""))
    assert got["top_focused_display"] is None and got["hints"] == ()


def test_a_line_that_only_dumpsys_window_prints_is_read_from_there(tmp_path):
    document = facts_json(tmp_path, THOR_WITHOUT_THE_LINE, PLAIN_DUMPSYS_WINDOW)
    assert document["top_focused_display"] == 0
    assert document.get("top_focused_display_inferred") is False
    assert UNKNOWN not in document["hints"]
    assert (tmp_path / "facts-window-all.json").exists()


def test_dumpsys_window_is_not_read_when_the_displays_dump_names_the_display(tmp_path):
    facts_json(tmp_path, THOR_WINDOW, PLAIN_DUMPSYS_WINDOW)
    assert not (tmp_path / "facts-window-all.json").exists()
    assert not json.loads((tmp_path / "facts-window.json").read_text())["input"]


def test_the_plain_dump_can_put_the_keys_on_another_display(tmp_path):
    document = facts_json(tmp_path, THOR_WITHOUT_THE_LINE, PLAIN_DUMPSYS_WINDOW.replace("=0", "=4"))
    assert document["top_focused_display"] == 4
    assert any(hint.startswith("Keys go to display 4, not display 0") for hint in document["hints"])


def test_the_card_says_the_display_was_inferred():
    inferred = card.facts_section(FACTS | {"top_focused_display_inferred": True})
    assert "| Keys go to display | 0 (inferred) |" in inferred
    assert "| Keys go to display | 0 |" in card.facts_section(FACTS)
