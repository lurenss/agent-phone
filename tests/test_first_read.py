import threading

import pytest
from fakes import J7_SERIAL, FakeHub, info_for, invoke
from support import FakeClock, fixture_screen, fixture_xml

from agent_phone.adapters.uiautomator2.first_read import MAX_AGE_S, FirstRead, overlap
from agent_phone.adapters.uiautomator2.phone import U2Phone
from agent_phone.adapters.uiautomator2.rpc import Phase, RpcResult
from agent_phone.cli.driver import open_phone
from agent_phone.cli.settings import Settings
from agent_phone.core.device import Connected
from agent_phone.core.outcome import ErrorCode, Refusal

J7 = Connected(J7_SERIAL, "SM_J730F", ready=True)
INFO = info_for(J7_SERIAL)


def test_the_facts_and_the_dump_run_at_the_same_time():
    dump_started = threading.Event()

    def facts():
        assert dump_started.wait(5), "the dump never started while the facts were being read"
        return INFO

    def dump():
        dump_started.set()
        return "<hierarchy />"

    info, first = overlap(facts, lambda: None, dump, FakeClock())
    assert info is INFO and first.text() == "<hierarchy />"


def test_a_refusal_from_the_dump_is_kept_for_the_first_read_and_not_raised():
    refusal = Refusal(ErrorCode.NO_SURFACE, "The screen dump is empty.")

    def dump():
        raise refusal

    info, first = overlap(lambda: INFO, lambda: None, dump, FakeClock())
    assert info is INFO and first.xml is None
    with pytest.raises(Refusal) as raised:
        first.text()
    assert raised.value is refusal


def test_a_refusal_from_the_facts_is_raised_after_the_dump_has_finished():
    finished = []

    def facts():
        raise Refusal(ErrorCode.TRANSPORT, "adb could not read the facts.")

    def dump():
        finished.append("dump")
        return "<hierarchy />"

    with pytest.raises(Refusal) as raised:
        overlap(facts, lambda: None, dump, FakeClock())
    assert raised.value.code is ErrorCode.TRANSPORT and finished == ["dump"]


def test_a_refusal_from_preparing_the_server_is_raised_after_the_facts_thread_has_finished():
    done = threading.Event()

    def facts():
        done.set()
        return INFO

    def prepare():
        raise Refusal(ErrorCode.SERVER_UNAVAILABLE, "The server did not start.")

    def dump():
        raise AssertionError("no dump is taken from a server that did not start")

    with pytest.raises(Refusal) as raised:
        overlap(facts, prepare, dump, FakeClock())
    assert raised.value.code is ErrorCode.SERVER_UNAVAILABLE and done.is_set()


class Rpc:
    def __init__(self):
        self.calls = 0

    def call(self, method, params):
        self.calls += 1
        return RpcResult(Phase.ANSWERED, fixture_xml("settings-home"), None)


class Forward:
    def close(self):
        pass


class Server:
    def touch(self):
        pass


def phone_with(first, clock):
    rpc = Rpc()
    return U2Phone(INFO, rpc, Forward(), Server(), 900, clock, None, first), rpc


def test_the_first_read_uses_the_dump_that_was_taken_early_and_every_later_read_asks_the_server():
    clock = FakeClock()
    phone, rpc = phone_with(FirstRead(fixture_xml("settings-home"), None, clock.now()), clock)
    assert phone.read() == fixture_screen("settings-home") and rpc.calls == 0
    phone.read()
    assert rpc.calls == 1


def test_a_dump_older_than_the_limit_is_not_used_so_a_session_never_reads_the_past():
    clock = FakeClock()
    phone, rpc = phone_with(FirstRead(fixture_xml("ig-feed"), None, clock.now()), clock)
    clock.pause(MAX_AGE_S + 0.1)
    assert phone.read() == fixture_screen("settings-home") and rpc.calls == 1


def test_a_kept_refusal_is_raised_by_the_first_read_once():
    clock = FakeClock()
    refusal = Refusal(ErrorCode.DEVICE_BUSY, "Another client holds the device.")
    phone, rpc = phone_with(FirstRead(None, refusal, clock.now()), clock)
    with pytest.raises(Refusal) as raised:
        phone.read()
    assert raised.value is refusal and rpc.calls == 0
    assert phone.read() == fixture_screen("settings-home") and rpc.calls == 1


@pytest.mark.parametrize(
    "argv",
    [["snapshot"], ["find", "--name", "x"], ["get", "@zzzzz:e1"], ["is", "@zzzzz:e1"]],
)
def test_a_command_that_reads_once_asks_the_hub_for_the_first_read(tmp_path, argv):
    hub = FakeHub([J7], screens=[fixture_screen("settings-home")])
    invoke(argv, hub, tmp_path)
    assert hub.first_read_asked == [True]


def test_a_session_does_not_ask_for_it_unless_it_says_so(tmp_path):
    hub = FakeHub([J7], screens=[fixture_screen("settings-home")])
    settings = Settings(state_root=tmp_path, lock_wait_s=0.0)
    with open_phone(hub=hub, settings=settings, clock=FakeClock()):
        pass
    with open_phone(hub=hub, settings=settings, clock=FakeClock(), first_read=True):
        pass
    assert hub.first_read_asked == [False, True]
