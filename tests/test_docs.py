"""docs/json-output.md is the contract agents read. These checks fail when a value is added to
an enum without the doc, or when the doc's example stops matching what the code prints."""

import json
import re

import pytest
from fakes import FakeHub, invoke
from support import GOLDEN, ROOT, fixture_screen, snapshot_of

from agent_phone.core.commands.get import GetProperty
from agent_phone.core.commands.is_ import IsProperty
from agent_phone.core.device import (
    BootId,
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
from agent_phone.core.outcome import Disposition, ErrorCode, Read
from agent_phone.core.phone import ServerStatus
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
        ("### Settle states", SettleState),
        ("### Get properties", GetProperty),
        ("### Is properties", IsProperty),
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
    assert to_wire("snapshot", identity.serial, Read(snapshot)) == example


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
        frozenset(),
    )
    rows = (
        Listed(Connected(info.identity.serial, "SM_J730F", True), info, None, None),
        Listed(Connected(Serial("R58M1234567"), "", False), None, None, None),
    )
    assert to_wire("devices", None, Read(DeviceList(rows))) == example


def test_the_devices_table_lists_exactly_the_keys_a_row_can_carry():
    info = DeviceInfo(
        DeviceIdentity(Serial("s"), BootId("b")), "m", 1, "abi", Size(1, 2), 3, "en", None, frozenset()
    )
    full = payload_data(DeviceList((Listed(Connected(Serial("s"), "m", True), info, "p", None),)))
    assert set(full["devices"][0]) == set(first_column("## Devices payload"))


def test_the_server_table_lists_exactly_the_keys_a_status_carries():
    assert set(payload_data(ServerStatus(True, True, 900, 3))) == set(first_column("## Server payload"))


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
