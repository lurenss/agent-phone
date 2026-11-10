"""`agent-phone flow record TRACE --out FILE`: the commands an agent ran by hand, read from the
device's trace of the day and written as the draft of a flow that replays them with no agent."""

import json
import tomllib

import pytest
from fakes import J7_SERIAL, FakeHub, invoke
from support import fixture_screen, node, screen_of, search_field

from agent_phone.core.device import Connected
from agent_phone.core.phone import Launch, SetText, Tap

pytestmark = pytest.mark.xfail(strict=True, reason="P3.7: flow record is not built yet")

J7 = Connected(J7_SERIAL, "SM_J730F", ready=True)
HOME = screen_of(
    node(
        "android.widget.FrameLayout",
        node("android.widget.TextView", text="Home screen", bounds="[0,200][1080,300]"),
        package="com.sec.android.app.launcher",
        bounds="[0,0][1080,1920]",
    )
)
SETTINGS = fixture_screen("settings-home")
NAMELESS = screen_of(
    node(
        "android.widget.FrameLayout",
        node("android.widget.ImageView", clickable=True, bounds="[0,200][200,400]"),
        package="com.android.settings",
        bounds="[0,0][1080,1920]",
    )
)


def ref_of(wire, words):
    return next(line.split()[0] for line in wire["data"]["tree"] if words in line)


def by_hand(root, typed="battery"):
    """What an agent does without a flow: look, launch, look again, type into the field by its ref."""
    hub = FakeHub([J7], screens=[HOME], after_each=[search_field(), search_field(typed)])
    invoke(["snapshot"], hub, root)
    invoke(["-d", J7_SERIAL, "launch", "com.android.settings"], hub, root)
    _, looked = invoke(["snapshot"], hub, root)
    code, _ = invoke(["set-text", ref_of(looked, "Search settings"), typed], hub, root)
    assert code == 0
    return hub


def trace(root):
    [path] = (root / "traces" / J7_SERIAL).iterdir()
    return path


def record(root, name="draft.toml"):
    out = root / name
    code, wire = invoke(["flow", "record", str(trace(root)), "--out", str(out)], FakeHub([]), root)
    return code, wire, out


def sent(hub):
    return [permit.action for phone in hub.phones for permit in phone.permits]


def test_a_recorded_settings_flow_replays_on_the_fake_phone(tmp_path):
    by_hand(tmp_path)
    code, wire, out = record(tmp_path)
    assert code == 0 and wire["ok"] is True and wire["command"] == "flow record" and wire["device"] is None
    assert wire["data"] == {"out": str(out), "steps": 2, "params": ["text"], "refs": []}
    draft = tomllib.loads(out.read_text())
    assert draft["flow"] == {"name": "draft", "grants": [], "params": ["text"]}
    assert [step["run"] for step in draft["step"]] == [
        ["launch", "com.android.settings"],
        ["set-text", 'role=field name="Search settings"', "{text}"],
    ]
    replay = FakeHub([J7], screens=[HOME], after_each=[search_field(), search_field("wifi")])
    code, wire = invoke(["flow", "run", str(out), "--param", "text=wifi"], replay, tmp_path / "replay")
    assert code == 0 and wire["data"]["ran"] == 2
    launch, typed = sent(replay)
    assert isinstance(launch, Launch) and isinstance(typed, SetText) and typed.text == "wifi"


def test_typed_text_becomes_a_parameter_and_is_never_written(tmp_path):
    hub = by_hand(tmp_path, typed="hunter2")
    invoke(["clipboard", "set", "hunter2"], hub, tmp_path)
    code, wire, out = record(tmp_path)
    assert code == 0 and wire["data"]["params"] == ["text", "text2"]
    assert "hunter2" not in out.read_text() and "hunter2" not in json.dumps(wire)
    assert tomllib.loads(out.read_text())["step"][2]["run"] == ["clipboard", "set", "{text2}"]


def test_reads_and_commands_that_failed_are_left_out_and_a_wait_stays(tmp_path):
    hub = FakeHub([J7], screens=[SETTINGS], after_each=[SETTINGS])
    invoke(["snapshot"], hub, tmp_path)
    invoke(["find", "--name", "Display"], hub, tmp_path)
    invoke(["click", "name=Nowhere", "--timeout-ms", "100"], hub, tmp_path)
    invoke(["click", "name=Display"], hub, tmp_path)
    invoke(["wait", "--for", "name=Display"], hub, tmp_path)
    invoke(["clipboard", "get"], hub, tmp_path)
    code, wire, out = record(tmp_path)
    assert code == 0 and wire["data"]["steps"] == 2
    assert [step["run"] for step in tomllib.loads(out.read_text())["step"]] == [
        ["click", "name=Display"],
        ["wait", "--for", "name=Display"],
    ]


def test_a_commit_the_agent_granted_becomes_a_grant_the_draft_declares(tmp_path):
    rule = tmp_path / "display.toml"
    rule.write_text(
        '[[commit]]\nid = "t.display"\neffect = "confirm"\nwords = ["display"]\n'
        'packages = ["com.android.settings"]\nreason = "A test commit."\n'
    )
    hub = FakeHub([J7], screens=[SETTINGS], after_each=[SETTINGS])
    invoke(["snapshot"], hub, tmp_path)
    click = ["click", "name=Display", "--policy", str(rule), "--commit", "confirm"]
    assert invoke(click, hub, tmp_path)[0] == 0
    _, _, out = record(tmp_path)
    draft = tomllib.loads(out.read_text())
    assert draft["flow"]["grants"] == ["confirm"] and draft["step"][0]["run"] == click
    replay = FakeHub([J7], screens=[SETTINGS], after_each=[SETTINGS])
    code, wire = invoke(["flow", "run", str(out)], replay, tmp_path / "replay")
    assert code == 1 and wire["error"]["code"] == "COMMIT_REFUSED" and replay.phones == []
    code, _ = invoke(["flow", "run", str(out), "--commit", "confirm"], replay, tmp_path / "replay")
    assert code == 0 and [type(action) for action in sent(replay)] == [Tap]


def test_a_ref_whose_target_has_no_name_stays_a_ref_and_the_envelope_points_at_it(tmp_path):
    hub = FakeHub([J7], screens=[NAMELESS], after_each=[NAMELESS])
    _, looked = invoke(["snapshot"], hub, tmp_path)
    ref = ref_of(looked, "button")
    assert invoke(["click", ref], hub, tmp_path)[0] == 0
    code, wire, out = record(tmp_path)
    assert code == 0 and wire["data"]["refs"] == [0]
    assert tomllib.loads(out.read_text())["step"][0]["run"] == ["click", ref]
    code, wire = invoke(["flow", "run", str(out)], hub, tmp_path / "replay")
    assert code == 2 and wire["error"]["code"] == "INVALID_ARGS", "the draft does not run until it is edited"


def test_the_lines_of_a_flow_run_and_a_command_that_died_are_not_recorded(tmp_path):
    by_hand(tmp_path)
    _, _, first = record(tmp_path, "first.toml")
    replay = FakeHub([J7], screens=[HOME], after_each=[search_field(), search_field("wifi")])
    assert invoke(["flow", "run", str(first), "--param", "text=wifi"], replay, tmp_path)[0] == 0
    with trace(tmp_path).open("a") as file:
        file.write('{"line":"begin","seq":99,"command":"press","argv":["press","back"],"started_utc":"x"}\n')
    _, wire, second = record(tmp_path, "second.toml")
    assert wire["data"]["steps"] == 2
    assert tomllib.loads(second.read_text())["step"] == tomllib.loads(first.read_text())["step"]


def test_a_draft_never_replaces_a_file_that_exists(tmp_path):
    by_hand(tmp_path)
    kept = tmp_path / "draft.toml"
    kept.write_text("mine")
    code, wire, out = record(tmp_path)
    assert code == 2 and wire["command"] == "flow record" and wire["error"]["code"] == "INVALID_ARGS"
    assert kept.read_text() == "mine"


@pytest.mark.parametrize("text", [None, "not json\n", '{"line":"begin"}\n', "[1]\n", ""])
def test_a_file_that_is_not_a_trace_or_has_nothing_to_replay_is_refused(tmp_path, text):
    path = tmp_path / "trace.jsonl"
    if text is not None:
        path.write_text(text)
    out = tmp_path / "draft.toml"
    code, wire = invoke(["flow", "record", str(path), "--out", str(out)], FakeHub([]), tmp_path)
    assert code == 2 and wire["command"] == "flow record" and wire["error"]["code"] == "INVALID_ARGS"
    assert not out.exists()
