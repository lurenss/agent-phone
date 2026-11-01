"""The uiautomator2 adapter sends each input as one call and says how far it got. The fake RPC
records every request, so "sent once" and "sent nothing" are observations."""

import base64
import shlex
from urllib.parse import quote, unquote

import pytest
from fakes import EMULATOR_SERIAL, J7_SERIAL, info_for
from support import FakeClock, fixture_xml
from test_u2_phone import Forward, Rpc, Server, Shell, answered, phone_with

from agent_phone.adapters.uiautomator2.adb import AdbResult
from agent_phone.adapters.uiautomator2.address import MASKS, selector_for
from agent_phone.adapters.uiautomator2.delivery import classify, classify_shell
from agent_phone.adapters.uiautomator2.phone import U2Phone
from agent_phone.adapters.uiautomator2.rpc import Phase, RpcResult
from agent_phone.adapters.uiautomator2.shell import Shell as AdbShell
from agent_phone.adapters.uiautomator2.shell import commands_for
from agent_phone.cli.policy import load_policy
from agent_phone.core.act.ledger import Ledger
from agent_phone.core.commands.open_url import OpenUrlCommand
from agent_phone.core.commands.open_url import run as open_url
from agent_phone.core.context import Context
from agent_phone.core.device import Package
from agent_phone.core.envelope import to_wire
from agent_phone.core.geometry import Point, Rect
from agent_phone.core.outcome import Acted, ErrorCode, Refusal, Refused
from agent_phone.core.phone import (
    Ack,
    Activate,
    Key,
    KeyName,
    Launch,
    LongPress,
    NodeAddress,
    NotSent,
    OpenUri,
    Orientation,
    Permit,
    Rotate,
    Sent,
    SetClipboard,
    SetText,
    Stop,
    Swipe,
    Tap,
    intent_of,
)
from agent_phone.core.policy.engine import Clear, ClearReason, Grant
from agent_phone.core.refs.store import SnapshotStore
from agent_phone.core.snapshot.capture import capture

FIELD = NodeAddress(
    Package("com.android.settings"),
    "android.widget.EditText",
    "android:id/search_src_text",
    "",
    "",
    Rect(150, 70, 900, 180),
    (0, 1),
    None,
)
INFO = info_for(J7_SERIAL)


def permit(action, device=INFO.identity):
    return Permit(device, 1, action, Clear(ClearReason.NO_COMMIT_WORDS), Grant.none())


def bounds(rect):
    return {"left": rect.left, "top": rect.top, "right": rect.right, "bottom": rect.bottom}


@pytest.mark.parametrize(
    ("reply", "expected"),
    [
        (RpcResult(Phase.NOT_CONNECTED, None, None), NotSent),
        (RpcResult(Phase.WRITTEN, None, None), Ack.UNACKNOWLEDGED),
        (
            RpcResult(
                Phase.ANSWERED, None, '{"message": "androidx.test.uiautomator.UiObjectNotFoundException"}'
            ),
            NotSent,
        ),
        (RpcResult(Phase.ANSWERED, None, '{"message": "UiAutomation not connected"}'), Ack.UNACKNOWLEDGED),
        (
            RpcResult(Phase.ANSWERED, None, '{"message": "android.os.DeadObjectException"}'),
            Ack.UNACKNOWLEDGED,
        ),
        (
            RpcResult(Phase.ANSWERED, None, '{"message": "java.lang.IllegalStateException"}'),
            Ack.UNACKNOWLEDGED,
        ),
        (answered(True), Ack.ACKNOWLEDGED),
    ],
)
def test_only_a_request_that_never_left_or_found_no_element_counts_as_not_sent(reply, expected):
    delivery = classify(reply)
    if expected is NotSent:
        assert isinstance(delivery, NotSent)
    else:
        assert isinstance(delivery, Sent) and delivery.ack is expected


def test_a_shell_input_is_not_sent_only_when_adb_never_started_or_said_nothing_started():
    assert isinstance(classify_shell(None, written=False), NotSent)
    refused = classify_shell(
        0, True, "Starting: Intent { act=x }\nError: Activity not started, unable to resolve"
    )
    assert isinstance(refused, NotSent) and refused.code is ErrorCode.NOT_FOUND
    assert isinstance(classify_shell(252, True, "** No activities found to run, monkey aborted."), NotSent)
    assert classify_shell(0, True, "Events injected: 1").ack is Ack.ACKNOWLEDGED
    assert classify_shell(1, True).ack is Ack.UNACKNOWLEDGED
    assert classify_shell(None, True).ack is Ack.UNACKNOWLEDGED


@pytest.mark.parametrize(
    ("action", "call"),
    [
        (Tap(Point(960, 995), FIELD), ("click", [960, 995])),
        (LongPress(Point(10, 20), FIELD, 800), ("click", [10, 20, 800])),
        (Swipe(Point(500, 900), Point(500, 300), 275), ("swipe", [500, 900, 500, 300, 55])),
        (Key(KeyName.BACK), ("pressKeyCode", [4])),
        (Key(KeyName.HOME), ("pressKeyCode", [3])),
        (Key(KeyName.RECENTS), ("pressKeyCode", [187])),
        (Key(KeyName.ENTER), ("pressKeyCode", [66])),
        (SetClipboard("hello"), ("setClipboard", [None, "hello"])),
    ],
)
def test_each_input_is_one_call_and_a_lost_answer_is_never_sent_again(action, call):
    rpc = Rpc(RpcResult(Phase.WRITTEN, None, None))
    delivery = phone_with(rpc).inject(permit(action))
    assert rpc.calls == [call]
    assert isinstance(delivery, Sent) and delivery.ack is Ack.UNACKNOWLEDGED


def test_a_permit_for_another_device_or_a_semantic_click_sends_nothing():
    rpc = Rpc(answered(True))
    phone = phone_with(rpc)
    other = info_for(EMULATOR_SERIAL).identity
    assert phone.inject(permit(Tap(Point(1, 1), FIELD), device=other)).code is ErrorCode.WRONG_DEVICE
    assert phone.inject(permit(Activate(FIELD))).code is ErrorCode.NOT_SUPPORTED
    assert rpc.calls == []


def test_an_app_level_input_goes_through_adb_shell():
    shell = Shell()
    phone = phone_with(Rpc(answered(True)), shell=shell)
    actions = [
        Launch(Package("com.android.settings")),
        Stop(Package("com.android.settings")),
        OpenUri("intent:#Intent;action=android.settings.DISPLAY_SETTINGS;end", None),
        Rotate(Orientation.AUTO),
    ]
    for action in actions:
        assert phone.inject(permit(action)).ack is Ack.ACKNOWLEDGED
    assert shell.ran == actions


def test_set_text_pins_the_one_field_with_the_read_bounds_and_always_names_its_instance():
    other = {"visibleBounds": bounds(Rect(150, 300, 900, 410))}
    mine = {"visibleBounds": bounds(FIELD.bounds)}
    rpc = Rpc(answered(2), answered(other), answered(mine), answered(True))
    assert phone_with(rpc).inject(permit(SetText(FIELD, "display", False))).ack is Ack.ACKNOWLEDGED
    plain = selector_for(FIELD)
    assert [method for method, _ in rpc.calls] == ["count", "objInfo", "objInfo", "setText"]
    assert rpc.calls[0][1] == [plain] and "text" not in plain and "instance" not in plain
    sent = rpc.calls[3][1]
    assert sent[1] == "display" and sent[0]["instance"] == 1 and sent[0]["mask"] & MASKS["instance"]
    alone = Rpc(answered(1), answered(mine), answered(True))
    phone_with(alone).inject(permit(SetText(FIELD, "display", False)))
    assert alone.calls[-1][1][0]["instance"] == 0 and alone.calls[-1][1][0]["mask"] & MASKS["instance"]


@pytest.mark.parametrize(
    ("replies", "code"),
    [
        ([answered(1), answered({"visibleBounds": bounds(Rect(0, 0, 10, 10))})], ErrorCode.STALE_REF),
        ([answered(0)], ErrorCode.STALE_REF),
        ([answered(2), answered({"bounds": bounds(FIELD.bounds)})], ErrorCode.AMBIGUOUS_TARGET),
        ([RpcResult(Phase.NOT_CONNECTED, None, None)], ErrorCode.SERVER_UNAVAILABLE),
    ],
)
def test_set_text_sends_no_text_unless_exactly_one_field_has_the_read_bounds(replies, code):
    rpc = Rpc(*replies)
    delivery = phone_with(rpc).inject(permit(SetText(FIELD, "display", False)))
    assert isinstance(delivery, NotSent) and delivery.code is code
    assert "setText" not in [method for method, _ in rpc.calls]


def test_the_shell_quotes_each_argument_so_a_link_stays_one_word():
    class Adb:
        def __init__(self):
            self.args = []

        def run(self, args, timeout_s=15.0):
            self.args.append(args)
            return AdbResult(0, "Starting: Intent", "")

    adb = Adb()
    link = OpenUri("https://example.com/?a=1&b=$(reboot)", Package("com.android.chrome"))
    assert AdbShell(J7_SERIAL, adb).run(link).ack is Ack.ACKNOWLEDGED
    script = adb.args[0][3]
    quoted = "'https://example.com/?a=1&b=$(reboot)'"
    assert script == f"am start -a android.intent.action.VIEW -d {quoted} -p com.android.chrome"


def test_each_app_level_input_is_the_command_that_does_only_it():
    settings = Package("com.android.settings")
    assert commands_for(Launch(settings)) == (
        ("monkey", "-p", settings, "-c", "android.intent.category.LAUNCHER", "1"),
    )
    assert commands_for(Stop(settings)) == (("am", "force-stop", settings),)
    intent = OpenUri(
        "intent:#Intent;action=android.settings.DISPLAY_SETTINGS;package=com.android.settings;end", None
    )
    assert commands_for(intent) == (
        ("am", "start", "-a", "android.settings.DISPLAY_SETTINGS", "-p", settings),
    )
    assert commands_for(Rotate(Orientation.LANDSCAPE)) == (
        ("settings", "put", "system", "accelerometer_rotation", "0"),
        ("settings", "put", "system", "user_rotation", "1"),
    )
    assert commands_for(Rotate(Orientation.AUTO)) == (
        ("settings", "put", "system", "accelerometer_rotation", "1"),
    )


def test_the_clipboard_and_a_screenshot_are_reads_of_the_server():
    phone = phone_with(Rpc(answered("copied")))
    assert phone.clipboard() == "copied"
    assert phone_with(Rpc(answered(None))).clipboard() is None
    with pytest.raises(Refusal):
        phone_with(Rpc(RpcResult(Phase.WRITTEN, None, None))).clipboard()
    image = phone_with(Rpc(answered(base64.b64encode(b"\xff\xd8jpeg").decode()))).screenshot()
    assert image == b"\xff\xd8jpeg"


def test_the_phone_reports_what_this_backend_can_do():
    phone = U2Phone(INFO, Rpc(), Forward(), Server(), 900, FakeClock(), Shell())
    assert {c.value for c in phone.info().capabilities} == {"clipboard", "screenshot"}


class AmStartAdb:
    """`adb shell am start -a VIEW -d <uri>`: starts the activity, exits 0, and prints the intent
    the way `Intent.toString()` does for a custom scheme, with the decoded link in it. It is a model
    of AOSP's ActivityManagerShellCommand, not a phone."""

    def __init__(self):
        self.scripts = []

    def run(self, args, timeout_s=15.0):
        self.scripts.append(args[3])
        argv = shlex.split(args[3])
        scheme, _, rest = argv[argv.index("-d") + 1].partition(":")
        return AdbResult(
            0, f"Starting: Intent {{ act={argv[argv.index('-a') + 1]} dat={scheme}:{unquote(rest)} }}\n", ""
        )


LINKS_WITH_A_BREAK = ["myapp:open%0AError:%20see%20docs", "myapp:open\nError: see docs", "myapp:a%E2%80%A8b"]
LINK_REFUSED_BEFORE_SENDING = pytest.mark.xfail(
    strict=True, reason="a link whose decoded text breaks a line reads as 'nothing started' when am echoes it"
)


def open_url_on(tmp_path, adb):
    phone = phone_with(Rpc(answered(fixture_xml("settings-home"))), shell=AdbShell(J7_SERIAL, adb))
    info = phone.info()
    ctx = Context(
        phone,
        info,
        None,
        load_policy(()),
        SnapshotStore(tmp_path),
        Ledger(tmp_path, info.identity),
        FakeClock(),
    )
    return ctx, capture(ctx, phone.read())


@LINK_REFUSED_BEFORE_SENDING
@pytest.mark.parametrize("uri", LINKS_WITH_A_BREAK)
def test_a_link_with_a_line_break_is_refused_before_anything_is_sent(tmp_path, uri):
    adb = AmStartAdb()
    ctx, before = open_url_on(tmp_path, adb)
    outcome = open_url(ctx, OpenUrlCommand(uri))
    assert adb.scripts == [], "am start ran, and its echo of the link can read as 'nothing started'"
    assert isinstance(outcome, Refused) and outcome.code is ErrorCode.INVALID_ARGS
    wire = to_wire("open-url", J7_SERIAL, outcome)
    assert (wire["delivery"], wire["retry"]) == ("not_delivered", "safe")
    assert ctx.ledger.epoch() == before.epoch, "a refused link spends nothing"


def test_a_link_that_opens_is_reported_as_sent_and_spends_the_refs(tmp_path):
    adb = AmStartAdb()
    ctx, before = open_url_on(tmp_path, adb)
    outcome = open_url(ctx, OpenUrlCommand("myapp:open%20the%20docs"))
    assert len(adb.scripts) == 1 and isinstance(outcome, Acted)
    assert ctx.ledger.epoch() == before.epoch + 1


@LINK_REFUSED_BEFORE_SENDING
def test_every_character_that_splits_a_line_or_is_a_control_character_refuses_a_link():
    splitting = [chr(i) for i in range(0x10000) if len(f"a{chr(i)}b".splitlines()) > 1]
    assert {"\n", "\r", "\x0b", "\x0c", "\x1c", "\x1d", "\x1e", "\x85", " ", " "} <= set(splitting)
    for char in (*splitting, *(chr(i) for i in range(0x20))):
        for uri in (f"myapp:a{char}b", f"myapp:a{quote(char)}b"):
            with pytest.raises(Refusal) as refused:
                intent_of(OpenUri(uri, None))
            assert refused.value.code is ErrorCode.INVALID_ARGS, repr(uri)


def test_a_link_with_encoded_text_that_is_no_control_character_is_still_opened():
    for uri in ("https://example.com/a%20b?q=%2F&r=%E2%9C%93", "myapp:open/path%3Fx", "tel:+39%20055%201234"):
        assert intent_of(OpenUri(uri, None)) is None


@LINK_REFUSED_BEFORE_SENDING
@pytest.mark.parametrize("action", [Launch(Package("a.b\nError: x")), Stop(Package("a.b\nError: x"))])
def test_no_shell_input_carries_a_line_break_to_adb(action):
    class Never:
        def run(self, args, timeout_s=15.0):
            raise AssertionError(f"adb ran {args}")

    delivery = AdbShell(J7_SERIAL, Never()).run(action)
    assert isinstance(delivery, NotSent) and delivery.code is ErrorCode.INVALID_ARGS


def test_the_clipboard_is_a_call_to_the_server_so_its_text_is_never_read_as_a_shell_error():
    rpc = Rpc(answered(True))
    text = "Error: nothing started\nNo activities found to run"
    delivery = phone_with(rpc).inject(permit(SetClipboard(text)))
    assert rpc.calls == [("setClipboard", [None, text])]
    assert isinstance(delivery, Sent) and delivery.ack is Ack.ACKNOWLEDGED
