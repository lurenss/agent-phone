"""`--lean`: the short form of an envelope. It is the full form with the bounds cut from each line
and without the keys that hold their usual value, so it says nothing the full form does not."""

import json
import re

from fakes import J7_SERIAL, FakeHub, invoke
from support import ROOT, node, screen_of

from agent_phone.core.device import Connected

J7 = Connected(J7_SERIAL, "SM_J730F", ready=True)


def page(*children):
    return screen_of(
        node(
            "android.widget.FrameLayout", *children, package="com.android.settings", bounds="[0,0][1080,1920]"
        )
    )


def button(name, top):
    return node("android.widget.Button", text=name, clickable=True, bounds=f"[0,{top}][1080,{top + 100}]")


BEFORE = page(button("Display", 300), button("Delete", 500))
AFTER = page(
    node("android.widget.TextView", text="Brightness", bounds="[0,700][1080,800]"), button("Back", 100)
)


def both(argv, tmp_path, **hub):
    """The full and the lean envelope of one command, each against its own fresh phone and state."""
    seen = []
    for at, extra in enumerate(([], ["--lean"])):
        root = tmp_path / str(at)
        code, wire = invoke(["snapshot"], FakeHub([J7], screens=[BEFORE]), root)
        assert code == 0
        command = [word.replace("@ID", f"@{wire['data']['id']}") for word in argv]
        seen.append(invoke([*command, *extra], FakeHub([J7], screens=[BEFORE], **hub), root))
    return seen


def without_ids(lines):
    return [" ".join(word for word in line.split(" ") if not word.startswith("@")) for line in lines]


def test_a_lean_snapshot_is_its_id_app_settle_state_and_lines_without_bounds(tmp_path):
    (_, full), (code, lean) = both(["snapshot", "--settle"], tmp_path)
    assert code == 0 and set(lean) == {"ok", "data"}
    assert set(lean["data"]) == {"id", "app", "settled", "tree"} and lean["data"]["settled"] == "settled"
    assert lean["data"]["tree"] == [
        f'@{lean["data"]["id"]}:e1 button "Display"',
        f'@{lean["data"]["id"]}:e2 button "Delete"',
    ]
    assert without_ids(lean["data"]["tree"]) == [
        line.rsplit(" [", 1)[0] for line in without_ids(full["data"]["tree"])
    ], "each lean line is the full line without its bounds"


def test_a_lean_input_keeps_its_delivery_and_the_screen_and_its_refs_still_work(tmp_path):
    (_, full), (code, lean) = both(["click", "@ID:e1", "--settle"], tmp_path, after_input=[AFTER])
    assert code == 0 and set(lean) == {"ok", "delivery", "data"} and lean["delivery"] == full["delivery"]
    after = lean["data"]["after"]
    assert set(lean["data"]) == {"after"} and after["tree"] == [
        'text "Brightness"',
        f'@{after["id"]}:e1 button "Back"',
    ]
    code, wire = invoke(["click", f"@{after['id']}:e1"], FakeHub([J7], screens=[AFTER]), tmp_path / "1")
    assert code == 0 and wire["data"]["target"]["name"] == "Back"


def test_lean_keeps_what_proved_an_input(tmp_path):
    click = ["click", "@ID:e1", "--wait-for", "name=Brightness"]
    (_, full), (_, lean) = both(click, tmp_path, after_input=[AFTER])
    assert lean["delivery"] == "delivered_verified"
    assert lean["data"]["verified_by"] == full["data"]["verified_by"] == 'present name="Brightness"'


def test_a_lean_error_keeps_its_code_message_hint_retry_and_the_last_screen(tmp_path):
    (_, full), (code, lean) = both(["click", "@ID:e2"], tmp_path)
    assert code == 1 and lean["error"]["code"] == "COMMIT_REFUSED" and lean["retry"] == "safe"
    assert lean["error"]["message"] == full["error"]["message"] and lean["error"]["hint"]
    assert lean["error"]["details"] == full["error"]["details"], "the effects to grant"
    (_, _), (code, lean) = both(["wait", "--for", "name=Never", "--timeout-ms", "200"], tmp_path / "wait")
    assert code == 1 and lean["error"]["code"] == "TIMEOUT"
    assert lean["error"]["details"]["after"]["tree"][0].endswith('button "Display"')


def test_lean_shows_every_key_that_does_not_hold_its_usual_value():
    from agent_phone.core.lean import lean

    snapshot = {
        "id": "q7m2k", "app": "a.b", "window": "dialog", "mode": "skeleton", "settled": "unsettled",
        "keyboard": True, "dialog": True, "truncated": 3, "toasts": ["Saved"],
        "others": [{"id": 0, "window": "system"}, {"id": 1, "window": "application"}],
        "interruptions": [{"kind": "permission", "dismiss": "@q7m2k:e2", "needs_human": False}],
        "tree": ['@q7m2k:e1 button "Allow" [0,0,10,10]', 'text "Brackets [1,2,3,4] inside"'],
    }  # fmt: skip
    gate = {"verdict": "commits", "effects": ["send"], "granted": [], "skipped": ["send"]}
    data = {"input": {"kind": "tap"}, "target": None, "gate": gate, "verified_by": None, "after": snapshot}
    wire = {"v": 1, "ok": True, "command": "click", "permission_mode": "dangerously-skip", "device": "x"}
    short = lean({**wire, "delivery": "delivered_unverified", "retry": "unsafe", "data": data})
    assert short["permission_mode"] == "dangerously-skip" and short["data"]["gate"] == gate
    after = short["data"]["after"]
    assert after == {
        **snapshot,
        "others": [{"id": 1, "window": "application"}],
        "tree": ['@q7m2k:e1 button "Allow"', 'text "Brackets [1,2,3,4] inside"'],
    }


def test_a_lean_batch_prints_each_step_lean(tmp_path):
    steps = [["snapshot"], ["click", "name=Display", "--settle"]]
    path = tmp_path / "steps.json"
    path.write_text(json.dumps(steps))
    hub = FakeHub([J7], screens=[BEFORE], after_input=[AFTER])
    code, wire = invoke(["batch", str(path), "--lean"], hub, tmp_path)
    assert code == 0 and wire["data"]["stopped_at"] is None
    assert wire["data"]["steps"][1]["data"]["after"]["tree"][0] == 'text "Brightness"'


def test_the_documented_lean_example_is_what_the_code_prints_for_its_screens(tmp_path):
    blocks = re.findall(r"```json\n(.*?)```", (ROOT / "docs" / "json-output.md").read_text(), re.S)
    example = next(wire for wire in map(json.loads, blocks) if "command" not in wire)
    (_, _), (_, lean) = both(["click", "@ID:e1", "--settle"], tmp_path, after_input=[AFTER])
    printed = json.dumps(lean).replace(lean["data"]["after"]["id"], example["data"]["after"]["id"])
    assert json.loads(printed) == example


def test_every_command_takes_lean_before_or_after_its_name(tmp_path):
    from agent_phone.cli.args import parse_args

    code, wire = invoke(["skills", "get", "reference", "--lean"], FakeHub([]))
    assert code == 0 and set(wire) == {"ok", "data"} and wire["data"]["name"] == "agent-phone-reference"
    code, wire = invoke(["--lean", "snapshot"], FakeHub([J7], screens=[BEFORE]), tmp_path)
    assert code == 0 and set(wire) == {"ok", "data"}
    for argv in (["skills", "list", "--lean"], ["flow", "record", "day.jsonl", "--out", "f.toml", "--lean"]):
        assert parse_args(argv).lean
    assert not parse_args(["snapshot"]).lean


def test_a_step_takes_no_lean_of_its_own(tmp_path):
    path = tmp_path / "steps.json"
    path.write_text(json.dumps([["snapshot", "--lean"]]))
    hub = FakeHub([J7], screens=[BEFORE])
    code, wire = invoke(["batch", str(path)], hub, tmp_path)
    assert code == 2 and wire["error"]["code"] == "INVALID_ARGS" and hub.phones == []
