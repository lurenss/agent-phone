"""What the engine reads for each kind of input, and that no kind can go unnamed. A kind that
`reads_of` forgot would read nothing, and so pass every deny rule."""

from typing import get_args

import pytest

from agent_phone.core.device import Package, Power
from agent_phone.core.geometry import Point, Rect
from agent_phone.core.phone import (
    Activate,
    InputAction,
    Key,
    KeyName,
    Launch,
    LongPress,
    NodeAddress,
    OpenUri,
    Orientation,
    Rotate,
    SetClipboard,
    SetPower,
    SetText,
    Stop,
    Swipe,
    Tap,
)
from agent_phone.core.policy.reads import Reads, reads_of

NODE = NodeAddress(Package("a.b"), "", "", "", "", Rect(0, 0, 1, 1), (), None)
EVERYTHING, DENIALS, NOTHING = Reads.EVERYTHING, Reads.DENIALS, Reads.NOTHING
READS = [
    (Tap(Point(0, 0), NODE), EVERYTHING),
    (LongPress(Point(0, 0), NODE, 800), EVERYTHING),
    (Activate(NODE), EVERYTHING),
    (Key(KeyName.ENTER), EVERYTHING),
    (SetText(NODE, "x", False), DENIALS),
    (Swipe(Point(0, 0), Point(0, 1), 275), DENIALS),
    (Key(KeyName.BACK), NOTHING),
    (Key(KeyName.HOME), NOTHING),
    (Key(KeyName.RECENTS), NOTHING),
    (Launch(Package("a.b")), NOTHING),
    (Stop(Package("a.b")), NOTHING),
    (OpenUri("https://example.com", None), NOTHING),
    (Rotate(Orientation.AUTO), NOTHING),
    (SetPower(Power.ON), NOTHING),
    (SetClipboard("x"), NOTHING),
]


@pytest.mark.parametrize(("action", "reads"), READS, ids=lambda value: type(value).__name__)
def test_each_input_is_read_as_far_as_what_it_does_allows(action, reads):
    assert reads_of(action) is reads


def test_every_kind_of_input_has_a_row_above():
    assert {type(action) for action, _ in READS} == set(get_args(InputAction)), (
        "a new kind of input needs a row here and a case in reads_of, and the row says what it reads"
    )


def test_a_kind_of_input_that_reads_of_does_not_name_fails_instead_of_reading_nothing():
    with pytest.raises(AssertionError):
        reads_of(object())  # type: ignore[arg-type]
