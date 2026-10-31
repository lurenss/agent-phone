"""docs/json-output.md is the contract agents read. These checks fail when a value is added to
an enum without the doc, or when the doc's example stops matching what the code prints."""

import json
import re

import pytest
from support import GOLDEN, ROOT

from agent_phone.core.outcome import Disposition, ErrorCode
from agent_phone.core.role import Role
from agent_phone.core.screen import WindowKind
from agent_phone.core.snapshot.snapshot import SettleState
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


@pytest.mark.parametrize(
    ("heading", "enum"),
    [
        ("## Delivery", Disposition),
        ("## Error codes", ErrorCode),
        ("### Roles", Role),
        ("### States", State),
        ("### Window kinds", WindowKind),
        ("### Settle states", SettleState),
    ],
)
def test_each_value_table_lists_exactly_its_enum(heading, enum):
    assert first_column(heading) == [member.value for member in enum]


def test_the_example_snapshot_is_what_the_code_prints_for_its_fixture():
    block = re.search(r"```json\n(.*?)```", CONTRACT, re.S).group(1)
    data = json.loads(block)["data"]
    assert set(data) == set(first_column("## Snapshot payload"))
    golden = (GOLDEN / "settings-home.compact.txt").read_text().splitlines()
    assert [line.replace(f"@{data['id']}:", "@t0000:") for line in data["tree"]] == golden
