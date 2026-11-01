"""`agent-phone wait` as an agent runs it: flags in, one envelope out, and nothing sent to the phone."""

import pytest
from fakes import J7_SERIAL, FakeHub, invoke
from support import fixture_screen, node, screen_of

from agent_phone.cli.args import parse_args
from agent_phone.core.commands.wait import WAIT_TIMEOUT_MS
from agent_phone.core.device import Connected, Package
from agent_phone.core.outcome import ErrorCode, Refusal
from agent_phone.core.query import Match, Q
from agent_phone.core.role import Role
from agent_phone.core.wait.predicate import Foreground, Gone, Present, Settled

pytestmark = pytest.mark.xfail(strict=True, reason="the wait command is not in the parser yet")

J7 = Connected(J7_SERIAL, "SM_J730F", ready=True)
SETTINGS = fixture_screen("settings-home")
BRIGHTNESS = screen_of(
    node(
        "android.widget.FrameLayout",
        node("android.widget.TextView", text="Brightness", bounds="[0,200][1080,300]"),
        package="com.android.settings",
        bounds="[0,0][1080,1920]",
    )
)
QUERIES = ["name=Brightness", 'name="Adaptive brightness"', "role=button name^=Dis", "text*=light", "id=list"]


def sent(hub):
    return [permit.action for phone in hub.phones for permit in phone.permits]


@pytest.mark.parametrize("query", QUERIES)
def test_for_and_gone_read_a_query_as_wait_for_and_wait_for_gone_do(query):
    waiting = parse_args(["wait", "--for", query, "--gone", query]).command
    acting = parse_args(["click", "@q7m2k:e1", "--wait-for", query, "--wait-for-gone", query]).command
    assert waiting.predicates == acting.wait_for and len(waiting.predicates) == 2


def test_every_flag_becomes_one_condition_and_the_timeout_has_a_default():
    shown, gone = Q("Brightness"), Q("Search", match=Match.PREFIX, role=Role.BUTTON)
    argv = ["wait", "--for", "name=Brightness", "--gone", "role=button name^=Search", "--settled"]
    argv += ["--app", "com.android.settings"]
    command = parse_args(argv).command
    assert command.predicates == (
        Present(shown),
        Gone(gone),
        Foreground(Package("com.android.settings")),
        Settled(),
    )
    assert command.timeout_ms == WAIT_TIMEOUT_MS
    assert parse_args(["wait", "--settled", "--timeout-ms", "250"]).command.timeout_ms == 250


def test_several_for_and_gone_flags_all_count():
    command = parse_args(["wait", "--for", "name=A", "--for", "name=B", "--gone", "name=C"]).command
    assert command.predicates == (Present(Q("A")), Present(Q("B")), Gone(Q("C")))


@pytest.mark.parametrize(
    "argv",
    [
        ["wait"],
        ["wait", "--timeout-ms", "500"],
        ["wait", "--for", "banana"],
        ["wait", "--for", "role=sofa"],
        ["wait", "--app", "not a package"],
        ["wait", "--settled", "--timeout-ms", "0"],
        ["wait", "--settled", "--timeout-ms", "soon"],
    ],
)
def test_a_wait_that_cannot_wait_is_invalid_args_before_the_phone_is_opened(tmp_path, argv):
    hub = FakeHub([J7], screens=[SETTINGS])
    code, wire = invoke(argv, hub, tmp_path)
    assert code == 2 and wire["error"]["code"] == ErrorCode.INVALID_ARGS.value
    assert "invalid choice" not in wire["error"]["message"], "wait is a command that refuses these arguments"
    assert wire["delivery"] == "not_delivered" and wire["retry"] == "safe"
    assert hub.phones == [] and hub.inspected == []


def test_no_condition_says_what_a_condition_is(tmp_path):
    _, wire = invoke(["wait"], FakeHub([J7]), tmp_path)
    assert "at least one condition" in wire["error"]["message"]


def test_a_condition_that_holds_prints_the_snapshot_it_held_on_after_one_read(tmp_path):
    hub = FakeHub([J7], screens=[SETTINGS])
    code, wire = invoke(["wait", "--for", "name=Display"], hub, tmp_path)
    assert code == 0 and wire["ok"] is True and wire["command"] == "wait" and wire["device"] == J7_SERIAL
    assert "delivery" not in wire and "error" not in wire
    assert wire["data"]["app"] == "com.android.settings" and wire["data"]["settled"] == "unchecked"
    assert any('button "Display"' in line for line in wire["data"]["tree"])
    assert hub.phones[0].reads == 1 and hub.first_read_asked == [True]
    assert sent(hub) == []


def test_a_settled_screen_in_the_foreground_says_settled(tmp_path):
    hub = FakeHub([J7], screens=[SETTINGS])
    code, wire = invoke(["wait", "--settled", "--app", "com.android.settings"], hub, tmp_path)
    assert code == 0 and wire["data"]["settled"] == "settled" and hub.phones[0].reads == 2


def test_a_timeout_prints_what_the_screen_showed_and_is_safe_to_retry(tmp_path):
    hub = FakeHub([J7], screens=[SETTINGS])
    code, wire = invoke(["wait", "--for", "name=Brightness", "--timeout-ms", "200"], hub, tmp_path)
    assert code == 1 and wire["ok"] is False and "data" not in wire
    assert wire["delivery"] == "not_delivered" and wire["retry"] == "safe"
    assert wire["error"]["code"] == "TIMEOUT"
    shown = wire["error"]["details"]["after"]
    assert shown["app"] == "com.android.settings"
    assert any('button "Display"' in line for line in shown["tree"])
    assert sent(hub) == []


def test_a_gone_for_something_never_there_holds_at_once(tmp_path):
    hub = FakeHub([J7], screens=[SETTINGS])
    code, wire = invoke(["wait", "--gone", "name=Brightness"], hub, tmp_path)
    assert code == 0 and wire["data"]["app"] == "com.android.settings" and hub.phones[0].reads == 1


def test_a_page_that_loads_while_it_waits_is_the_read_it_returns(tmp_path):
    hub = FakeHub([J7], screens=[SETTINGS, SETTINGS, BRIGHTNESS])
    code, wire = invoke(["wait", "--for", "name=Brightness", "--gone", "name=Display"], hub, tmp_path)
    assert code == 0 and wire["data"]["tree"] == ['text "Brightness" [0,200,1080,300]']
    assert hub.phones[0].reads == 3


def test_a_ref_from_wait_serves_the_next_input_and_a_new_wait_serves_the_one_after(tmp_path):
    hub = FakeHub([J7], screens=[SETTINGS], after_input=[BRIGHTNESS])
    _, waited = invoke(["wait", "--for", "name=Display"], hub, tmp_path)
    tile = next(line for line in waited["data"]["tree"] if 'button "Display"' in line).split()[0]
    code, clicked = invoke(["click", tile], hub, tmp_path)
    assert code == 0 and clicked["delivery"] == "delivered_unverified"
    code, blind = invoke(["press", "back"], hub, tmp_path)
    assert code == 1 and blind["error"]["code"] == "OBSERVE_FIRST"
    code, _ = invoke(["wait", "--for", "name=Display"], hub, tmp_path)
    assert code == 0
    code, pressed = invoke(["press", "back"], hub, tmp_path)
    assert code == 0 and pressed["delivery"] == "delivered_unverified"
    assert len(sent(hub)) == 2


def test_a_read_that_fails_is_the_error_the_read_gave(tmp_path):
    hub = FakeHub([J7], screens=[Refusal(ErrorCode.TRANSPORT, "the server did not answer")])
    code, wire = invoke(["wait", "--settled"], hub, tmp_path)
    assert code == 1 and wire["error"]["code"] == "TRANSPORT" and wire["delivery"] == "not_delivered"
