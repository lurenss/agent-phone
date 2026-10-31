"""Each redacted fixture against its expected compact snapshot.

Regenerate after an intended change with `AGENT_PHONE_UPDATE_GOLDENS=1 uv run pytest tests/test_golden.py`,
then read the diff line by line against the fixture before committing it.
"""

import os

import pytest
from support import FIXTURES, GOLDEN, fixture_screen

from agent_phone.core.snapshot.budget import fit, render
from agent_phone.core.snapshot.snapshot import SnapshotId
from agent_phone.core.snapshot.surface import select_surface
from agent_phone.core.snapshot.view import Mode, build_view

ID = SnapshotId("t0000")


@pytest.mark.parametrize("name", FIXTURES)
def test_fixture_renders_its_golden_compact_snapshot(name):
    view = fit(build_view(select_surface(fixture_screen(name)), Mode.COMPACT), ID)
    text = "\n".join(render(view, ID)) + "\n"
    path = GOLDEN / f"{name}.compact.txt"
    if os.environ.get("AGENT_PHONE_UPDATE_GOLDENS"):
        path.parent.mkdir(exist_ok=True)
        path.write_text(text)
    assert text == path.read_text()
