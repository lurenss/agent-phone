import pytest
from fakes import J7_SERIAL, info_for
from support import FakeClock, fixture_screen, fixture_xml

from agent_phone.adapters.uiautomator2.phone import DUMP_METHOD, U2Phone
from agent_phone.adapters.uiautomator2.rpc import Phase, RpcResult
from agent_phone.core.outcome import ErrorCode, Refusal
from agent_phone.core.phone import Ack, Sent

IDLE_LIMIT_S = 900


class Rpc:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    def call(self, method, params):
        self.calls.append((method, params))
        return self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]


class Forward:
    closed = 0

    def close(self):
        self.closed += 1


class Server:
    def __init__(self):
        self.touched = 0

    def touch(self):
        self.touched += 1


class Shell:
    def __init__(self):
        self.ran = []

    def run(self, action):
        self.ran.append(action)
        return Sent(Ack.ACKNOWLEDGED, "exit 0")


def phone_with(rpc, clock=None, server=None, shell=None):
    return U2Phone(
        info_for(J7_SERIAL),
        rpc,
        Forward(),
        server or Server(),
        IDLE_LIMIT_S,
        clock or FakeClock(),
        shell or Shell(),
    )


def answered(result):
    return RpcResult(Phase.ANSWERED, result, None)


def test_a_read_asks_for_the_whole_hierarchy_once_and_parses_it():
    rpc = Rpc(answered(fixture_xml("settings-home")))
    screen = phone_with(rpc).read()
    assert rpc.calls == [(DUMP_METHOD, [False, 50])]
    assert screen == fixture_screen("settings-home")


@pytest.mark.parametrize(
    ("reply", "code"),
    [
        (RpcResult(Phase.NOT_CONNECTED, None, None), ErrorCode.SERVER_UNAVAILABLE),
        (RpcResult(Phase.WRITTEN, None, None), ErrorCode.SERVER_UNAVAILABLE),
        (
            RpcResult(Phase.ANSWERED, None, '{"message": "UiAutomation not connected"}'),
            ErrorCode.SERVER_UNAVAILABLE,
        ),
        (RpcResult(Phase.ANSWERED, None, "UiAutomationService already registered!"), ErrorCode.DEVICE_BUSY),
        (answered(""), ErrorCode.NO_SURFACE),
        (answered('<hierarchy rotation="0" />'), ErrorCode.NO_SURFACE),
        (answered(42), ErrorCode.TRANSPORT),
        (answered("<hierarchy"), ErrorCode.TRANSPORT),
    ],
)
def test_a_read_that_goes_wrong_is_refused_with_the_code_that_says_what_to_do(reply, code):
    with pytest.raises(Refusal) as raised:
        phone_with(Rpc(reply)).read()
    assert raised.value.code is code


def test_a_failed_read_is_never_sent_twice_by_the_adapter():
    rpc = Rpc(RpcResult(Phase.WRITTEN, None, None))
    with pytest.raises(Refusal):
        phone_with(rpc).read()
    assert len(rpc.calls) == 1


def test_use_is_counted_at_most_once_per_interval_so_a_long_session_keeps_its_server():
    clock, server = FakeClock(), Server()
    phone = phone_with(Rpc(answered(fixture_xml("settings-home"))), clock, server)
    for _ in range(3):
        phone.read()
    assert server.touched == 0, "opening counted as a use"
    clock.time = 59
    phone.read()
    assert server.touched == 0
    clock.time = 61
    phone.read()
    phone.read()
    assert server.touched == 1
    clock.time = 130
    phone.read()
    assert server.touched == 2


def test_closing_releases_the_forward_and_nothing_else():
    forward, server = Forward(), Server()
    U2Phone(info_for(J7_SERIAL), Rpc(), forward, server, IDLE_LIMIT_S, FakeClock(), Shell()).close()
    assert forward.closed == 1 and server.touched == 0
