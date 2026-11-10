"""docs/json-output.md is the contract agents read. These checks fail when a value is added to
an enum without the doc, or when the doc's example stops matching what the code prints."""

import json
import re
import tomllib

import pytest
from fakes import FakeHub, invoke
from support import GOLDEN, ROOT, fixture_screen, node, screen_of, search_field, snapshot_of

from agent_phone.cli.settings import Settings
from agent_phone.core.commands.get import GetProperty
from agent_phone.core.commands.is_ import IsProperty
from agent_phone.core.device import (
    BootId,
    Capability,
    Connected,
    DeviceIdentity,
    DeviceInfo,
    DeviceList,
    Listed,
    Package,
    Serial,
)
from agent_phone.core.envelope import payload_data, to_wire
from agent_phone.core.geometry import Size
from agent_phone.core.outcome import Disposition, ErrorCode, Read, Refusal, Refused
from agent_phone.core.phone import ServerStatus
from agent_phone.core.policy.engine import ClearReason
from agent_phone.core.policy.mode import PermissionMode
from agent_phone.core.policy.model import InterruptionKind
from agent_phone.core.policy.rules import Effect
from agent_phone.core.role import Role
from agent_phone.core.screen import WindowKind
from agent_phone.core.snapshot.snapshot import SettleState, SnapshotId
from agent_phone.core.snapshot.view import State

CONTRACT = (ROOT / "docs" / "json-output.md").read_text()


def first_column(heading):
    """The backticked first cell of each row of the table under `heading`."""
    lines = CONTRACT.splitlines()
    cells = []
    for line in lines[lines.index(heading) + 1 :]:
        if line.startswith("#"):
            break
        if line.startswith("| `"):
            cells.append(line.split("|")[1].strip().strip("`"))
    return cells


def json_blocks():
    return [json.loads(block) for block in re.findall(r"```json\n(.*?)```", CONTRACT, re.S)]


@pytest.mark.parametrize(
    ("heading", "enum"),
    [
        ("## Delivery", Disposition),
        ("## Error codes", ErrorCode),
        ("### Roles", Role),
        ("### States", State),
        ("### Window kinds", WindowKind),
        ("### Interruption kinds", InterruptionKind),
        ("### Settle states", SettleState),
        ("### Get properties", GetProperty),
        ("### Is properties", IsProperty),
        ("### Clear reasons", ClearReason),
        ("### Effects", Effect),
        ("### Permission modes", PermissionMode),
    ],
)
def test_each_value_table_lists_exactly_its_enum(heading, enum):
    assert first_column(heading) == [member.value for member in enum]


def test_the_example_snapshot_is_what_the_code_prints_for_its_fixture():
    example = next(block for block in json_blocks() if block["command"] == "snapshot")
    data = example["data"]
    assert set(data) == set(first_column("## Snapshot payload"))
    golden = (GOLDEN / "settings-home.compact.txt").read_text().splitlines()
    assert [line.replace(f"@{data['id']}:", "@t0000:") for line in data["tree"]] == golden
    identity = DeviceIdentity(Serial(example["device"]), BootId("0"))
    snapshot = snapshot_of(fixture_screen("settings-home"), SnapshotId(data["id"]), identity)
    assert to_wire("snapshot", identity.serial, Read(snapshot), mode=PermissionMode.ASK) == example


def test_the_example_device_list_is_what_the_code_prints():
    example = next(block for block in json_blocks() if block["command"] == "devices")
    listed = example["data"]["devices"][0]
    ready, not_ready = (row["ready"] for row in example["data"]["devices"])
    assert ready and not not_ready
    info = DeviceInfo(
        DeviceIdentity(Serial(listed["serial"]), BootId(listed["boot_id"])),
        listed["model"],
        listed["api"],
        listed["abi"],
        Size(*listed["display"]),
        listed["density"],
        listed["locale"],
        Package(listed["ime"]),
        frozenset(Capability(name) for name in listed["capabilities"]),
    )
    rows = (
        Listed(Connected(info.identity.serial, "SM_J730F", True), info, None, None),
        Listed(Connected(Serial("R58M1234567"), "", False), None, None, None),
    )
    assert to_wire("devices", None, Read(DeviceList(rows)), mode=PermissionMode.ASK) == example


def test_the_devices_table_lists_exactly_the_keys_a_row_can_carry():
    info = DeviceInfo(
        DeviceIdentity(Serial("s"), BootId("b")), "m", 1, "abi", Size(1, 2), 3, "en", None, frozenset()
    )
    full = payload_data(DeviceList((Listed(Connected(Serial("s"), "m", True), info, "p", None),)))
    assert set(full["devices"][0]) == set(first_column("## Devices payload"))


def test_the_server_table_lists_exactly_the_keys_a_status_carries():
    assert set(payload_data(ServerStatus(True, True, 900, 3))) == set(first_column("## Server payload"))


def test_the_skills_tables_list_exactly_the_keys_list_and_get_carry(tmp_path):
    _, listed = invoke(["skills", "list"], FakeHub([]), tmp_path)
    assert set(listed["data"]) == {"skills"}
    assert set(listed["data"]["skills"][0]) == set(first_column("### Skills list"))
    _, got = invoke(["skills", "get"], FakeHub([]), tmp_path)
    assert set(got["data"]) == set(first_column("### Skills get"))


def test_the_example_find_is_what_the_code_prints_for_its_fixture(tmp_path):
    example = next(block for block in json_blocks() if block["command"] == "find")
    assert set(example["data"]) == set(first_column("## Find payload"))
    hub = FakeHub(
        [Connected(Serial(example["device"]), "SM_J730F", True)], screens=[fixture_screen("settings-home")]
    )
    code, wire = invoke(["find", "--name", "connections"], hub, tmp_path)
    printed = json.dumps(wire, ensure_ascii=False).replace(wire["data"]["id"], example["data"]["id"])
    assert code == 0 and json.loads(printed) == example


def test_the_find_table_lists_exactly_the_keys_a_find_carries(tmp_path):
    hub = FakeHub(
        [Connected(Serial("0a1b2c3d4e5f6a7b"), "SM_J730F", True)], screens=[fixture_screen("settings-home")]
    )
    _, wire = invoke(["find", "--name", "connections"], hub, tmp_path)
    assert set(wire["data"]) == set(first_column("## Find payload"))
    _, counted = invoke(["find", "--name", "connections", "--count"], hub, tmp_path)
    assert set(counted["data"]) == {"count"}


def test_the_example_get_is_what_the_code_prints_for_its_fixture(tmp_path):
    example = next(block for block in json_blocks() if block["command"] == "get")
    assert set(example["data"]) == set(first_column("## Get and is payload"))
    hub = FakeHub(
        [Connected(Serial(example["device"]), "SM_J730F", True)], screens=[fixture_screen("settings-home")]
    )
    _, taken = invoke(["snapshot"], hub, tmp_path)
    ref = f"@{taken['data']['id']}:e4"
    code, wire = invoke(["get", ref, "--property", "bounds"], hub, tmp_path)
    printed = json.dumps(wire, ensure_ascii=False).replace(taken["data"]["id"], "p4n8c")
    assert code == 0 and json.loads(printed) == example
    code, checked = invoke(["is", ref], hub, tmp_path)
    assert set(checked["data"]) == set(first_column("## Get and is payload"))


def test_the_example_click_is_what_the_code_prints_for_its_fixture(tmp_path):
    example = next(block for block in json_blocks() if block["command"] == "click" and block["ok"])
    assert set(example["data"]) == set(first_column("## Input payload"))
    hub = FakeHub(
        [Connected(Serial(example["device"]), "SM_J730F", True)], screens=[fixture_screen("settings-home")]
    )
    _, taken = invoke(["snapshot"], hub, tmp_path)
    code, wire = invoke(["click", f"@{taken['data']['id']}:e7"], hub, tmp_path)
    printed = json.dumps(wire, ensure_ascii=False).replace(taken["data"]["id"], "q7m2k")
    assert code == 0 and json.loads(printed) == example


def test_the_example_refused_commit_is_what_the_code_prints(tmp_path):
    example = next(block for block in json_blocks() if block.get("error", {}).get("code") == "COMMIT_REFUSED")
    schedule = screen_of(
        node(
            "android.widget.FrameLayout",
            node("android.widget.Button", text="Schedule reel", clickable=True, bounds="[0,1700][1080,1800]"),
            bounds="[0,0][1080,1920]",
        )
    )
    hub = FakeHub([Connected(Serial(example["device"]), "SM_J730F", True)], screens=[schedule])
    _, taken = invoke(["snapshot"], hub, tmp_path)
    code, wire = invoke(["click", f"@{taken['data']['id']}:e1"], hub, tmp_path)
    assert code == 1 and wire == example


def test_the_example_skipped_commit_is_what_the_code_prints(tmp_path):
    example = next(block for block in json_blocks() if block.get("permission_mode") == "dangerously-skip")
    schedule = screen_of(
        node(
            "android.widget.FrameLayout",
            node("android.widget.Button", text="Schedule reel", clickable=True, bounds="[0,1700][1080,1800]"),
            bounds="[0,0][1080,1920]",
        )
    )
    hub = FakeHub([Connected(Serial(example["device"]), "SM_J730F", True)], screens=[schedule])
    _, taken = invoke(["snapshot"], hub, tmp_path)
    skip = {"AGENT_PHONE_PERMISSION_MODE": "dangerously-skip"}
    code, wire = invoke(["click", f"@{taken['data']['id']}:e1"], hub, tmp_path, env=skip)
    printed = json.dumps(wire, ensure_ascii=False).replace(taken["data"]["id"], "m9q4t")
    assert code == 0 and json.loads(printed) == example
    assert set(example["data"]["gate"]) == {"verdict", "effects", "granted", "skipped"}


def test_the_example_invalid_mode_is_what_the_code_prints():
    example = next(
        block
        for block in json_blocks()
        if block.get("permission_mode") is None and "permission_mode" in block
    )
    with pytest.raises(Refusal) as refused:
        Settings.from_environment({"AGENT_PHONE_PERMISSION_MODE": "skip"})
    assert to_wire("", None, Refused.of(refused.value), mode=None) == example


def test_the_example_wait_timeout_is_what_the_code_prints_for_its_fixture(tmp_path):
    example = next(block for block in json_blocks() if block["command"] == "wait")
    assert set(example["error"]["details"]["after"]) == set(first_column("## Snapshot payload"))
    hub = FakeHub(
        [Connected(Serial(example["device"]), "SM_J730F", True)], screens=[fixture_screen("settings-home")]
    )
    code, wire = invoke(["wait", "--for", "name=Brightness", "--timeout-ms", "200"], hub, tmp_path)
    id = wire["error"]["details"]["after"]["id"]
    printed = json.dumps(wire, ensure_ascii=False).replace(id, example["error"]["details"]["after"]["id"])
    assert code == 1 and json.loads(printed) == example


def test_the_example_flow_is_what_the_code_prints_for_the_example_file(tmp_path):
    example = next(block for block in json_blocks() if block["command"] == "flow run")
    assert list(example["data"]) == first_column("## Flow payload")
    [written] = re.findall(r"```toml\n(.*?)```", CONTRACT, re.S)
    shipped = (ROOT / "examples" / "flows" / "settings-search.toml").read_text()
    assert tomllib.loads(written) == tomllib.loads(shipped)
    file_keys = [f"flow.{key}" for key in tomllib.loads(written)["flow"]] + ["step.run", "step.expect"]
    assert first_column("### Flow file") == file_keys
    file = tmp_path / "flow.toml"
    file.write_text(written)
    j7 = Connected(Serial(example["device"]), "SM_J730F", True)
    hub = FakeHub(
        [j7], screens=[fixture_screen("settings-home")], after_each=[search_field(), search_field("battery")]
    )
    code, wire = invoke(["flow", "run", str(file), "--param", "query=battery"], hub, tmp_path)
    wire["data"]["trace"] = example["data"]["trace"]
    assert code == 0 and wire == example


def test_the_example_flow_record_is_what_the_code_prints(tmp_path):
    example = next(block for block in json_blocks() if block["command"] == "flow record")
    assert list(example["data"]) == first_column("### Flow record")
    j7 = Connected(Serial("0a1b2c3d4e5f6a7b"), "SM_J730F", True)
    hub = FakeHub([j7], screens=[search_field()], after_input=[search_field("battery")])
    invoke(["snapshot"], hub, tmp_path)
    invoke(["launch", "com.android.settings"], hub, tmp_path)
    invoke(["snapshot"], hub, tmp_path)
    invoke(["set-text", "name=Search settings", "battery"], hub, tmp_path)
    [trace] = (tmp_path / "traces" / "0a1b2c3d4e5f6a7b").iterdir()
    out = tmp_path / "settings-search.toml"
    code, wire = invoke(["flow", "record", str(trace), "--out", str(out)], hub, tmp_path)
    wire["data"]["out"] = out.name
    assert code == 0 and wire == example


def run_batch(tmp_path, steps, serial="0a1b2c3d4e5f6a7b"):
    """The envelope and the trace lines of a batch on the Settings fixture, after one snapshot."""
    hub = FakeHub([Connected(Serial(serial), "SM_J730F", True)], screens=[fixture_screen("settings-home")])
    _, taken = invoke(["snapshot"], hub, tmp_path)
    file = tmp_path / "steps.json"
    file.write_text(json.dumps(steps))
    code, wire = invoke(["batch", str(file)], hub, tmp_path)
    lines = [json.loads(line) for line in open(wire["data"]["trace"]).read().splitlines()]
    return code, wire, lines, taken["data"]["id"]


def test_the_example_batch_is_what_the_code_prints(tmp_path):
    example = next(block for block in json_blocks() if block["command"] == "batch")
    assert set(example["data"]) == set(first_column("## Batch payload"))
    steps = [["launch", "com.android.settings"], ["click", "name=Nowhere", "--timeout-ms", "100"]]
    code, wire, _, taken = run_batch(tmp_path, steps, example["device"])
    printed = json.dumps(wire, ensure_ascii=False).replace(taken, "e8j9h")
    printed = printed.replace(wire["data"]["trace"], example["data"]["trace"])
    assert code == 1 and json.loads(printed) == example


def test_the_trace_tables_list_exactly_the_keys_a_line_carries(tmp_path):
    _, _, lines, _ = run_batch(tmp_path, [["launch", "com.android.settings"], ["press", "back"]])
    step, end = lines[0], lines[-1]
    assert list(step) == first_column("#### Trace step line")
    assert list(end) == first_column("#### Trace end line")


def test_the_example_trace_has_the_keys_of_the_tables():
    block, _ = re.findall(r"```jsonl\n(.*?)```", CONTRACT, re.S)
    *steps, end = [json.loads(line) for line in block.splitlines()]
    assert all(list(step) == first_column("#### Trace step line") for step in steps)
    assert list(end) == first_column("#### Trace end line")


def test_the_command_trace_tables_list_exactly_the_keys_a_line_carries(tmp_path):
    j7 = Connected(Serial("0a1b2c3d4e5f6a7b"), "SM_J730F", True)
    hub = FakeHub([j7], screens=[search_field()], after_input=[search_field("hunter2")])
    invoke(["snapshot"], hub, tmp_path)
    invoke(["set-text", "name=Search settings", "hunter2"], hub, tmp_path)
    [file] = (tmp_path / "traces" / "0a1b2c3d4e5f6a7b").iterdir()
    written = [json.loads(line) for line in file.read_text().splitlines()]
    _, block = re.findall(r"```jsonl\n(.*?)```", CONTRACT, re.S)
    example = [json.loads(line) for line in block.splitlines()]
    for line in (*written, *example):
        assert list(line) == first_column(f"#### Command {line['line']} line")
    stable = ("line", "seq", "command", "argv", "ok", "delivery", "error", "input", "target", "gate")
    assert [{k: v for k, v in line.items() if k in stable} for line in written] == [
        {k: v for k, v in line.items() if k in stable} for line in example
    ]
