"""`delivered_verified` means the input caused the change: an effect wait proves an input only when
it was false on the read the input was planned on and holds after it. Each claim about what was sent
is checked against the fake's `permits` and the ledger's epoch."""

import tomllib

import pytest
from fakes import J7_SERIAL, FakePhone, info_for
from support import FakeClock, fixture_screen, node, screen_of

from agent_phone.cli.policy import DEFAULT_POLICY
from agent_phone.core.act.act import act
from agent_phone.core.act.intent import Click, Request
from agent_phone.core.act.ledger import Ledger
from agent_phone.core.context import Context
from agent_phone.core.outcome import Disposition, ErrorCode, Refused, disposition_of
from agent_phone.core.phone import Key, KeyName
from agent_phone.core.policy.rules import merge, parse_policy
from agent_phone.core.query import Q
from agent_phone.core.refs.resolve import RefTarget
from agent_phone.core.refs.store import SnapshotStore
from agent_phone.core.snapshot.capture import capture
from agent_phone.core.snapshot.snapshot import SettleState
from agent_phone.core.wait.predicate import Gone, Present

POLICY = merge((parse_policy(tomllib.loads(DEFAULT_POLICY.read_text(encoding="utf-8")), "default.toml"),))
SETTINGS = fixture_screen("settings-home")
DISPLAY_TILE = 7
DISPLAY_PAGE = screen_of(
    node(
        "android.widget.FrameLayout",
        node("android.widget.TextView", text="Brightness", bounds="[0,200][1080,300]"),
        package="com.android.settings",
        bounds="[0,0][1080,1920]",
    )
)


def context(root, *screens, **fake):
    info = info_for(J7_SERIAL)
    phone = FakePhone(info, *screens, **fake)
    ctx = Context(phone, info, None, POLICY, SnapshotStore(root), Ledger(root, info.identity), FakeClock())
    return ctx, phone


def tap_display(ctx, *wait_for, timeout_ms=300):
    taken = capture(ctx, ctx.phone.read(), settled=SettleState.UNCHECKED)
    return Request(Click(RefTarget(taken.ref(DISPLAY_TILE))), wait_for=wait_for, timeout_ms=timeout_ms)


def press_back(ctx, *wait_for):
    capture(ctx, ctx.phone.read(), settled=SettleState.UNCHECKED)
    return Request(Key(KeyName.BACK), wait_for=wait_for, timeout_ms=300)


@pytest.mark.parametrize(
    "request_for",
    [
        lambda ctx: tap_display(ctx, Present(Q("Notifications"))),
        lambda ctx: tap_display(ctx, Gone(Q("Brightness"))),
        lambda ctx: press_back(ctx, Present(Q("Display"))),
    ],
    ids=["present on a tap", "gone on a tap", "present on a key"],
)
def test_an_effect_wait_that_already_holds_is_refused_and_sends_nothing(tmp_path, request_for):
    ctx, phone = context(tmp_path, SETTINGS, after_input=[DISPLAY_PAGE])
    outcome = act(ctx, request_for(ctx))
    assert isinstance(outcome, Refused) and outcome.code is ErrorCode.INVALID_ARGS, outcome
    assert disposition_of(outcome) is Disposition.NOT_DELIVERED
    assert phone.permits == [] and ctx.ledger.epoch() == 0
