"""A backend says whether it can touch a point on the screen. One that cannot gets no tap, long
press or swipe: core refuses each with NOT_SUPPORTED before it spends a permit."""

import pytest
from fakes import J7_SERIAL, info_for
from test_act import DISPLAY_TILE, SETTINGS, context, look, refused

from agent_phone.core.act.act import act
from agent_phone.core.act.intent import Click, Direction, Request, Scroll
from agent_phone.core.device import Capability
from agent_phone.core.geometry import Point
from agent_phone.core.outcome import ErrorCode
from agent_phone.core.refs.resolve import PointTarget, RefTarget

TILES = 3


@pytest.mark.xfail(
    strict=True, raises=AssertionError, reason="#3: core taps a backend that cannot touch a point"
)
def test_a_backend_without_point_input_refuses_every_input_at_a_point_and_sends_nothing(tmp_path):
    info = info_for(J7_SERIAL, capabilities=frozenset({Capability.CLIPBOARD, Capability.SCREENSHOT}))
    ctx, phone = context(tmp_path, SETTINGS, info=info)
    taken = look(ctx)
    for intent in (
        Click(PointTarget(taken.id, Point(540, 300))),
        Click(RefTarget(taken.ref(DISPLAY_TILE))),
        Click(RefTarget(taken.ref(DISPLAY_TILE)), long=True),
        Scroll(RefTarget(taken.ref(TILES)), Direction.DOWN),
    ):
        refused(act(ctx, Request(intent)), ErrorCode.NOT_SUPPORTED)
    assert phone.permits == [] and ctx.ledger.epoch() == 0
