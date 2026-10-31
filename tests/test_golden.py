"""Each redacted fixture against its expected snapshot, in each mode and surface that has a golden.

Regenerate after an intended change with `AGENT_PHONE_UPDATE_GOLDENS=1 uv run pytest tests/test_golden.py`,
then read the diff line by line against the fixture before committing it.
"""

import os

import pytest
from support import FIXTURES, GOLDEN, fixture_screen

from agent_phone.core.snapshot.budget import fit, render
from agent_phone.core.snapshot.snapshot import SnapshotId
from agent_phone.core.snapshot.surface import Pick, select_surface
from agent_phone.core.snapshot.view import Mode, build_view

ID = SnapshotId("t0000")

CASES = [(name, mode, Pick.ACTIVE) for mode in (Mode.COMPACT, Mode.SKELETON) for name in FIXTURES] + [
    ("ig-feed", Mode.COMPACT, Pick.ALL),
    ("ig-feed", Mode.SKELETON, Pick.ALL),
    ("dialog-over-app", Mode.COMPACT, Pick.ALL),
    ("dialog-over-app", Mode.COMPACT, Pick.DIALOG),
    ("notification-shade", Mode.COMPACT, Pick.SHADE),
]


def golden_name(name, mode, pick):
    return f"{name}.{mode.value}.txt" if pick is Pick.ACTIVE else f"{name}.{mode.value}.{pick.value}.txt"


@pytest.mark.parametrize(
    ("name", "mode", "pick"), CASES, ids=[golden_name(*case).removesuffix(".txt") for case in CASES]
)
def test_fixture_renders_its_golden_snapshot(name, mode, pick):
    view = fit(build_view(select_surface(fixture_screen(name), pick=pick), mode), ID)
    text = "\n".join(render(view, ID)) + "\n"
    path = GOLDEN / golden_name(name, mode, pick)
    if os.environ.get("AGENT_PHONE_UPDATE_GOLDENS"):
        path.parent.mkdir(exist_ok=True)
        path.write_text(text)
    assert text == path.read_text()
