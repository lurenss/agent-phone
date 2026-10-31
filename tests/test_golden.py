"""Each redacted fixture against its expected snapshot, in each mode that has a golden.

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

PAGER_HIDES_THE_PAGE = pytest.mark.xfail(
    strict=True, reason="the skeleton folds the page pager, and its one row holds the whole feed"
)

CASES = [
    pytest.param(
        name,
        mode,
        id=f"{name}-{mode.value}",
        marks=[PAGER_HIDES_THE_PAGE] if (name, mode) == ("ig-feed", Mode.SKELETON) else [],
    )
    for mode in (Mode.COMPACT, Mode.SKELETON)
    for name in FIXTURES
]


@pytest.mark.parametrize(("name", "mode"), CASES)
def test_fixture_renders_its_golden_snapshot(name, mode):
    view = fit(build_view(select_surface(fixture_screen(name)), mode), ID)
    text = "\n".join(render(view, ID)) + "\n"
    path = GOLDEN / f"{name}.{mode.value}.txt"
    if os.environ.get("AGENT_PHONE_UPDATE_GOLDENS"):
        path.parent.mkdir(exist_ok=True)
        path.write_text(text)
    assert text == path.read_text()
