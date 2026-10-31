from support import FakeClock

from agent_phone.core.wait.until import until


def test_it_returns_what_the_attempt_returns_without_waiting():
    clock = FakeClock()
    assert until(clock, lambda: "ready", timeout_s=5) == "ready"
    assert clock.pauses == []


def test_it_polls_until_the_attempt_succeeds():
    clock = FakeClock()
    answers = iter([None, None, "up"])
    assert until(clock, lambda: next(answers), timeout_s=5, gap_s=0.5) == "up"
    assert clock.pauses == [0.5, 0.5]


def test_it_gives_up_at_the_deadline():
    clock = FakeClock()
    assert until(clock, lambda: None, timeout_s=2, gap_s=0.5) is None
    assert 2 <= clock.time <= 2.5


def test_a_zero_timeout_still_tries_once():
    clock = FakeClock()
    calls = []
    assert until(clock, lambda: calls.append(1), timeout_s=0) is None
    assert len(calls) == 1 and clock.pauses == []
