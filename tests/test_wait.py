"""`wait` on a fake phone: when it returns, what it returns, and that it never sends anything.

Every claim about "sends no input" is checked against the fake's `permits`, the list of inputs the
backend received, and against the ledger's epoch, which every spent permit advances."""

import json
import tomllib

import pytest
from fakes import J7_SERIAL, FakePhone, info_for
from support import FakeClock, fixture_screen, node, screen_of

from agent_phone.cli.policy import DEFAULT_POLICY
from agent_phone.core.act import ledger
from agent_phone.core.act.act import act
from agent_phone.core.act.intent import Request
from agent_phone.core.act.ledger import Ledger
from agent_phone.core.commands.wait import WaitCommand, run
from agent_phone.core.context import Context
from agent_phone.core.device import Package
from agent_phone.core.envelope import encode, to_wire
from agent_phone.core.outcome import Disposition, ErrorCode, Read, Refusal, Refused
from agent_phone.core.phone import Key, KeyName
from agent_phone.core.policy.rules import merge, parse_policy
from agent_phone.core.query import Q
from agent_phone.core.refs.store import SnapshotStore
from agent_phone.core.snapshot.snapshot import RefToken, SettleState, Snapshot, SnapshotId
from agent_phone.core.wait.clock import POLL_GAP_S
from agent_phone.core.wait.predicate import Foreground, Gone, Present, Settled

POLICY = merge((parse_policy(tomllib.loads(DEFAULT_POLICY.read_text(encoding="utf-8")), "default.toml"),))
SETTINGS = fixture_screen("settings-home")
SETTINGS_PACKAGE = Package("com.android.settings")


def page(*names):
    """A Settings window that shows each name as a line of text."""
    rows = [
        node("android.widget.TextView", text=name, bounds=f"[0,{i * 100}][1080,{i * 100 + 90}]")
        for i, name in enumerate(names)
    ]
    return screen_of(
        node("android.widget.FrameLayout", *rows, package="com.android.settings", bounds="[0,0][1080,1920]")
    )


def context(root, *screens):
    info = info_for(J7_SERIAL)
    phone = FakePhone(info, *screens)
    clock = FakeClock()
    ctx = Context(phone, info, None, POLICY, SnapshotStore(root), Ledger(root, info.identity), clock)
    return ctx, phone, clock


def names(snapshot):
    return [line.name for line in snapshot.lines]


def timed_out(outcome):
    assert isinstance(outcome, Refused) and outcome.code is ErrorCode.TIMEOUT, outcome
    return outcome


def test_a_condition_that_already_holds_returns_the_first_read_at_once(tmp_path):
    ctx, phone, clock = context(tmp_path, page("Display", "Brightness"))
    done = run(ctx, WaitCommand((Present(Q("Brightness")),)))
    assert isinstance(done, Read) and isinstance(done.payload, Snapshot)
    assert names(done.payload) == ["Display", "Brightness"]
    assert phone.reads == 1 and clock.pauses == []


def test_it_needs_no_snapshot_taken_before_it(tmp_path):
    ctx, _, _ = context(tmp_path, page("Brightness"))
    assert ctx.store.latest(J7_SERIAL) is None
    assert isinstance(run(ctx, WaitCommand((Present(Q("Brightness")),))), Read)


def test_a_condition_that_holds_after_some_reads_returns_the_read_it_held_on(tmp_path):
    ctx, phone, clock = context(tmp_path, SETTINGS, SETTINGS, page("Display", "Brightness"))
    done = run(ctx, WaitCommand((Present(Q("Brightness")),)))
    assert isinstance(done, Read)
    assert names(done.payload) == ["Display", "Brightness"]
    assert phone.reads == 3 and clock.pauses == [POLL_GAP_S, POLL_GAP_S]


def test_the_snapshot_is_recorded_so_its_refs_work_for_the_next_command(tmp_path):
    ctx, _, _ = context(tmp_path, SETTINGS)
    done = run(ctx, WaitCommand((Present(Q("Display")),)))
    assert isinstance(done, Read)
    assert ctx.store.latest(J7_SERIAL) == done.payload
    assert done.payload.epoch == ctx.ledger.epoch()
    assert any(line.ref is not None for line in done.payload.lines)


def test_after_an_input_it_records_the_observation_that_the_next_input_needs(tmp_path):
    ctx, phone, _ = context(tmp_path, SETTINGS)
    run(ctx, WaitCommand((Foreground(SETTINGS_PACKAGE),)))
    back = Request(Key(KeyName.BACK))
    assert act(ctx, back).disposition is Disposition.DELIVERED_UNVERIFIED
    blind = act(ctx, back)
    assert isinstance(blind, Refused) and blind.code is ErrorCode.OBSERVE_FIRST
    done = run(ctx, WaitCommand((Foreground(SETTINGS_PACKAGE),)))
    assert isinstance(done, Read) and done.payload.epoch == ctx.ledger.epoch() == 1
    assert act(ctx, back).disposition is Disposition.DELIVERED_UNVERIFIED
    assert len(phone.permits) == 2


def test_a_timeout_is_refused_and_carries_the_last_read(tmp_path):
    ctx, phone, clock = context(tmp_path, SETTINGS)
    outcome = timed_out(run(ctx, WaitCommand((Present(Q("Brightness")),), timeout_ms=500)))
    after = outcome.details["after"]
    assert isinstance(after, Snapshot) and after.package == SETTINGS_PACKAGE
    assert "Display" in names(after)
    assert ctx.store.latest(J7_SERIAL) == after and after.epoch == ctx.ledger.epoch()
    assert 'present name="Brightness"' in outcome.message and "500 ms" in outcome.message
    assert 0.5 <= clock.time <= 0.5 + POLL_GAP_S
    assert phone.reads == len(clock.pauses) + 1


def test_a_timeout_with_nothing_to_describe_is_still_a_timeout(tmp_path):
    status_bar_only = screen_of(
        node("android.widget.FrameLayout", package="com.android.systemui", bounds="[0,0][1080,60]")
    )
    ctx, _, _ = context(tmp_path, status_bar_only)
    outcome = timed_out(run(ctx, WaitCommand((Present(Q("Brightness")),), timeout_ms=100)))
    assert outcome.details == {"after": None}


def test_a_read_that_fails_is_refused_as_it_is_and_not_called_a_timeout(tmp_path):
    ctx, _, _ = context(tmp_path, Refusal(ErrorCode.TRANSPORT, "the server did not answer"))
    outcome = run(ctx, WaitCommand((Present(Q("Brightness")),)))
    assert isinstance(outcome, Refused) and outcome.code is ErrorCode.TRANSPORT


def test_every_condition_must_hold_on_the_same_read(tmp_path):
    saving, saved, nothing = page("Saving", "Saved"), page("Saved"), page("Other")
    ctx, phone, _ = context(tmp_path, saving, nothing, saved)
    both = (Present(Q("Saved")), Gone(Q("Saving")))
    done = run(ctx, WaitCommand(both))
    assert isinstance(done, Read) and names(done.payload) == ["Saved"] and phone.reads == 3


def test_conditions_that_hold_on_different_reads_never_hold_together(tmp_path):
    saving_and_saved, other = page("Saving", "Saved"), page("Other")
    flicker = [saving_and_saved if i % 2 == 0 else other for i in range(200)]
    ctx, _, _ = context(tmp_path, *flicker)
    both = (Present(Q("Saved")), Gone(Q("Saving")))
    timed_out(run(ctx, WaitCommand(both, timeout_ms=500)))


def test_gone_holds_at_once_for_something_that_was_never_there(tmp_path):
    ctx, phone, clock = context(tmp_path, SETTINGS)
    done = run(ctx, WaitCommand((Gone(Q("A dialog that never opened")),)))
    assert isinstance(done, Read) and phone.reads == 1 and clock.pauses == []


def test_the_foreground_app_is_the_window_that_has_focus(tmp_path):
    ctx, _, _ = context(tmp_path, SETTINGS)
    assert isinstance(run(ctx, WaitCommand((Foreground(SETTINGS_PACKAGE),))), Read)
    timed_out(run(ctx, WaitCommand((Foreground(Package("com.example.other")),), timeout_ms=100)))


def test_settled_needs_two_reads_that_print_the_same_lines(tmp_path):
    ctx, phone, _ = context(tmp_path, SETTINGS)
    done = run(ctx, WaitCommand((Settled(),)))
    assert isinstance(done, Read) and done.payload.settled is SettleState.SETTLED and phone.reads == 2


def test_a_wait_that_asks_for_no_settle_says_unchecked(tmp_path):
    ctx, _, _ = context(tmp_path, SETTINGS)
    done = run(ctx, WaitCommand((Present(Q("Display")),)))
    assert isinstance(done, Read) and done.payload.settled is SettleState.UNCHECKED


def test_no_condition_is_invalid_args_and_reads_nothing(tmp_path):
    ctx, phone, _ = context(tmp_path, SETTINGS)
    outcome = run(ctx, WaitCommand(()))
    assert isinstance(outcome, Refused) and outcome.code is ErrorCode.INVALID_ARGS
    assert phone.reads == 0


def test_a_gone_by_ref_is_not_supported_and_sends_nothing(tmp_path):
    ctx, phone, _ = context(tmp_path, SETTINGS)
    outcome = run(ctx, WaitCommand((Gone(RefToken(SnapshotId("q7m2k"), 4)),)))
    assert isinstance(outcome, Refused) and outcome.code is ErrorCode.NOT_SUPPORTED
    assert phone.permits == []


@pytest.mark.parametrize(
    "command",
    [
        WaitCommand((Present(Q("Display")),)),
        WaitCommand((Present(Q("Brightness")),), timeout_ms=200),
        WaitCommand((Settled(), Foreground(SETTINGS_PACKAGE))),
        WaitCommand(()),
    ],
    ids=["held at once", "timed out", "settled and foreground", "no condition"],
)
def test_a_wait_spends_no_permit_and_sends_no_input(tmp_path, command):
    ctx, phone, _ = context(tmp_path, SETTINGS)
    run(ctx, command)
    assert phone.permits == [] and ctx.ledger.epoch() == 0 and ledger.UNREFUNDED == []


def test_a_timeout_prints_the_last_read_and_is_safe_to_retry(tmp_path):
    ctx, _, _ = context(tmp_path, SETTINGS)
    outcome = run(ctx, WaitCommand((Present(Q("Brightness")),), timeout_ms=200))
    wire = to_wire("wait", J7_SERIAL, outcome)
    assert wire["ok"] is False and wire["delivery"] == "not_delivered" and wire["retry"] == "safe"
    assert wire["error"]["code"] == "TIMEOUT"
    shown = json.loads(encode(wire))["error"]["details"]["after"]
    assert shown == to_wire("snapshot", J7_SERIAL, Read(outcome.details["after"]))["data"]
    assert shown["app"] == "com.android.settings"


def test_a_wait_that_held_prints_like_a_snapshot(tmp_path):
    ctx, _, _ = context(tmp_path, SETTINGS)
    done = run(ctx, WaitCommand((Present(Q("Display")),)))
    wire = to_wire("wait", J7_SERIAL, done)
    assert wire["ok"] is True and wire["command"] == "wait" and "delivery" not in wire
    assert wire["data"] == to_wire("snapshot", J7_SERIAL, done)["data"]
