"""`--after diff`: an input's `after` prints what the screen gained and lost since the snapshot the
input stood on, in place of the tree. The snapshot is still recorded, so an added line's ref works."""

import json
import re

import pytest
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


TITLE = node("android.widget.TextView", text="Settings", bounds="[0,0][1080,100]")
BEFORE = page(TITLE, button("Search", 100), button("Display", 300))
AFTER = page(
    TITLE,
    button("Back", 100),
    button("Search", 500),
    node("android.widget.TextView", text="Brightness", bounds="[0,700][1080,800]"),
)
DIFF = pytest.mark.xfail(strict=True, reason="P2.9: --after diff is not built yet")


def snapshot(root):
    code, wire = invoke(["snapshot"], FakeHub([J7], screens=[BEFORE]), root)
    assert code == 0 and wire["data"]["tree"][2].startswith(f'@{wire["data"]["id"]}:e2 button "Display"')
    return wire["data"]["id"]


def recorded(root):
    return sorted(path.name for path in root.rglob("snapshots/*"))


@DIFF
def test_after_diff_lists_only_the_lines_the_input_changed(tmp_path):
    taken = snapshot(tmp_path)
    click = ["click", f"@{taken}:e2", "--wait-for", "name=Brightness", "--after", "diff"]
    code, wire = invoke(click, FakeHub([J7], screens=[BEFORE], after_input=[AFTER]), tmp_path)
    assert code == 0 and wire["delivery"] == "delivered_verified"
    after = wire["data"]["after"]
    assert "tree" not in after
    assert after["kept"] == 2, "the title, and Search, whose ref went from e1 to e2 and whose place moved"
    assert after["added"] == [
        f'@{after["id"]}:e1 button "Back" [0,100,1080,200]',
        'text "Brightness" [0,700,1080,800]',
    ]
    assert after["gone"] == ['button "Display"']
    code, wire = invoke(["click", f"@{after['id']}:e1"], FakeHub([J7], screens=[AFTER]), tmp_path)
    assert code == 0 and wire["data"]["target"]["name"] == "Back", "an added line's ref is a recorded ref"


@DIFF
def test_after_diff_reads_records_and_proves_what_the_tree_does_and_prints_less(tmp_path):
    seen = {}
    for form in ("tree", "diff"):
        root = tmp_path / form
        click = ["click", f"@{snapshot(root)}:e2", "--wait-for", "name=Brightness", "--after", form]
        hub = FakeHub([J7], screens=[BEFORE], after_input=[AFTER])
        _, wire = invoke(click, hub, root)
        size = len(json.dumps(wire["data"]["after"]))
        seen[form] = (hub.phones[0].reads, len(recorded(root)), wire["delivery"], size)
    assert seen["diff"][:3] == seen["tree"][:3] and seen["diff"][3] < seen["tree"][3]


@DIFF
def test_after_diff_records_no_snapshot_where_the_input_recorded_none(tmp_path):
    taken = snapshot(tmp_path)
    before = recorded(tmp_path)
    hub = FakeHub([J7], screens=[BEFORE], after_input=[AFTER])
    code, wire = invoke(["click", f"@{taken}:e2", "--after", "diff"], hub, tmp_path)
    assert code == 0 and wire["data"]["after"] is None
    assert recorded(tmp_path) == before and hub.phones[0].reads == 2, "no read and no snapshot was added"


@DIFF
def test_a_diff_that_shows_a_change_does_not_verify_the_input(tmp_path):
    taken = snapshot(tmp_path)
    hub = FakeHub([J7], screens=[BEFORE], after_input=[AFTER])
    click = ["click", f"@{taken}:e2", "--wait-for", "name=Never", "--timeout-ms", "300", "--after", "diff"]
    code, wire = invoke(click, hub, tmp_path)
    assert code == 1 and wire["error"]["code"] == "TIMEOUT"
    assert wire["data"]["after"]["added"] and wire["data"]["after"]["gone"]
    assert wire["delivery"] == "delivered_unverified" and wire["data"]["verified_by"] is None


@DIFF
def test_a_batch_step_takes_after_diff_like_a_command_alone(tmp_path):
    steps = [["snapshot"], ["click", "name=Display", "--wait-for", "name=Brightness", "--after", "diff"]]
    path = tmp_path / "steps.json"
    path.write_text(json.dumps(steps))
    hub = FakeHub([J7], screens=[BEFORE], after_input=[AFTER])
    code, wire = invoke(["batch", str(path)], hub, tmp_path)
    assert code == 0
    assert wire["data"]["steps"][1]["data"]["after"]["gone"] == ['button "Display"']


@DIFF
def test_after_diff_prints_the_tree_when_the_input_replaced_the_screen(tmp_path):
    taken = snapshot(tmp_path)
    other = page(node("android.widget.TextView", text="Brightness", bounds="[0,700][1080,800]"))
    click = ["click", f"@{taken}:e2", "--wait-for", "name=Brightness", "--after", "diff"]
    code, wire = invoke(click, FakeHub([J7], screens=[BEFORE], after_input=[other]), tmp_path)
    assert code == 0 and wire["data"]["after"]["tree"] == ['text "Brightness" [0,700,1080,800]']
    assert not {"kept", "added", "gone"} & set(wire["data"]["after"]), "a diff would list both screens"


@DIFF
def test_a_second_line_equal_to_a_kept_one_is_added(tmp_path):
    taken = snapshot(tmp_path)
    twice = page(TITLE, button("Search", 100), button("Search", 300), button("Display", 500))
    click = ["click", f"@{taken}:e1", "--wait-for", "name=Never", "--timeout-ms", "300", "--after", "diff"]
    _, wire = invoke(click, FakeHub([J7], screens=[BEFORE], after_input=[twice]), tmp_path)
    after = wire["data"]["after"]
    assert (after["kept"], after["gone"]) == (3, [])
    assert after["added"] == [f'@{after["id"]}:e2 button "Search" [0,300,1080,400]']


@DIFF
def test_the_documented_diff_is_what_the_code_prints_for_its_screens(tmp_path):
    blocks = re.findall(r"```json\n(.*?)```", (ROOT / "docs" / "json-output.md").read_text(), re.S)
    example = next(
        wire for wire in map(json.loads, blocks) if "kept" in (wire.get("data", {}).get("after") or {})
    )
    taken = snapshot(tmp_path)
    click = ["click", f"@{taken}:e2", "--wait-for", "name=Brightness", "--after", "diff"]
    _, wire = invoke(click, FakeHub([J7], screens=[BEFORE], after_input=[AFTER]), tmp_path)
    ids = {taken: "fky1a", wire["data"]["after"]["id"]: example["data"]["after"]["id"]}
    printed = json.dumps(wire)
    for real, documented in ids.items():
        printed = printed.replace(real, documented)
    assert json.loads(printed) == example


@DIFF
def test_of_two_equal_lines_the_one_at_a_new_place_is_the_added_one(tmp_path):
    taken = snapshot(tmp_path)
    above = page(TITLE, button("Search", 700), button("Search", 100), button("Display", 300))
    click = ["click", f"@{taken}:e1", "--wait-for", "name=Never", "--timeout-ms", "300", "--after", "diff"]
    _, wire = invoke(click, FakeHub([J7], screens=[BEFORE], after_input=[above]), tmp_path)
    after = wire["data"]["after"]
    assert after["added"] == [f'@{after["id"]}:e1 button "Search" [0,700,1080,800]']


@DIFF
def test_after_diff_prints_the_tree_when_the_earlier_snapshot_is_in_another_mode(tmp_path):
    code, full = invoke(["snapshot", "--full"], FakeHub([J7], screens=[BEFORE]), tmp_path)
    ref = next(line.split()[0] for line in full["data"]["tree"] if '"Display"' in line)
    click = ["click", ref, "--wait-for", "name=Brightness", "--after", "diff"]
    code, wire = invoke(click, FakeHub([J7], screens=[BEFORE], after_input=[AFTER]), tmp_path)
    assert code == 0 and "tree" in wire["data"]["after"] and "gone" not in wire["data"]["after"]
