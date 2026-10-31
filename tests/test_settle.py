import pytest
from fakes import J7_SERIAL, FakeHub, invoke
from support import FakeClock, fixture_screen, node, screen_of

from agent_phone.cli.driver import open_phone
from agent_phone.cli.settings import Settings
from agent_phone.core.device import Connected
from agent_phone.core.snapshot.snapshot import SettleState
from agent_phone.core.wait.clock import POLL_GAP_S
from agent_phone.core.wait.observe import observe

J7 = Connected(J7_SERIAL, "SM_J730F", ready=True)


def screen_saying(title, icon_bounds="[0,0][10,10]"):
    return screen_of(
        node(
            "android.widget.FrameLayout",
            node("android.widget.TextView", text=title),
            node("android.widget.ImageView", bounds=icon_bounds),
            bounds="[0,0][1080,1920]",
        )
    )


def settle(screens, tmp_path, timeout_ms=3000):
    hub = FakeHub([J7], screens=screens)
    clock = FakeClock()
    settings = Settings(state_root=tmp_path, lock_wait_s=0.0)
    with open_phone(hub=hub, settings=settings, clock=clock) as phone:
        taken = phone.snapshot(settle=True, timeout_ms=timeout_ms)
    return taken, hub.phones[0].reads, clock


def test_a_screen_that_does_not_change_is_settled_after_two_reads(tmp_path):
    taken, reads, clock = settle([screen_saying("Wi-Fi")], tmp_path)
    assert taken.settled is SettleState.SETTLED and reads == 2
    assert clock.pauses == [POLL_GAP_S]


def test_a_screen_that_changes_once_settles_on_the_new_content(tmp_path):
    old, new = screen_saying("Settings"), screen_saying("Wi-Fi")
    taken, reads, _ = settle([old, new], tmp_path)
    assert taken.settled is SettleState.SETTLED and reads == 3
    assert [line.name for line in taken.lines] == ["Wi-Fi"]


def test_a_screen_that_never_stops_changing_is_unsettled_and_the_last_read_is_described(tmp_path):
    flicker = [screen_saying("A" if i % 2 == 0 else "B") for i in range(200)]
    taken, reads, clock = settle(flicker, tmp_path, timeout_ms=500)
    assert taken.settled is SettleState.UNSETTLED
    assert reads == len(clock.pauses) + 1
    assert 0.5 <= clock.time <= 0.5 + POLL_GAP_S
    assert [line.name for line in taken.lines] == ["AB"[(reads - 1) % 2]]


def test_a_change_the_agent_cannot_see_does_not_unsettle_a_screen(tmp_path):
    taken, reads, _ = settle([screen_saying("Wi-Fi"), screen_saying("Wi-Fi", "[0,0][20,20]")], tmp_path)
    assert taken.settled is SettleState.SETTLED and reads == 2


def test_a_deadline_already_past_returns_the_one_read_it_made(tmp_path):
    taken, reads, _ = settle([screen_saying("Wi-Fi")], tmp_path, timeout_ms=0)
    assert taken.settled is SettleState.UNSETTLED and reads == 1


def test_observe_without_a_settle_predicate_reports_unchecked(tmp_path):
    hub = FakeHub([J7], screens=[screen_saying("Wi-Fi")])
    settings = Settings(state_root=tmp_path, lock_wait_s=0.0)
    with open_phone(hub=hub, settings=settings, clock=FakeClock()) as phone:
        seen = observe(phone._ctx, (), 0.0)
    assert seen.held and seen.settled is SettleState.UNCHECKED and seen.reads == 1


def test_a_snapshot_without_settle_reads_once_and_says_unchecked(tmp_path):
    hub = FakeHub([J7], screens=[fixture_screen("settings-home")])
    code, wire = invoke(["snapshot"], hub, tmp_path)
    assert code == 0 and wire["data"]["settled"] == "unchecked" and hub.phones[0].reads == 1


def test_settle_on_the_command_line_says_settled_and_reads_twice(tmp_path):
    hub = FakeHub([J7], screens=[fixture_screen("settings-home")])
    code, wire = invoke(["snapshot", "--settle"], hub, tmp_path)
    assert code == 0 and wire["data"]["settled"] == "settled" and hub.phones[0].reads == 2


def test_settle_with_a_short_timeout_on_a_flickering_screen_still_prints_a_snapshot(tmp_path):
    flicker = [screen_saying("A" if i % 2 == 0 else "B") for i in range(200)]
    hub = FakeHub([J7], screens=flicker)
    code, wire = invoke(["snapshot", "--settle", "--timeout-ms", "200"], hub, tmp_path)
    assert (
        code == 0
        and wire["data"]["settled"] == "unsettled"
        and wire["data"]["tree"] == ['text "A" [0,0,100,100]']
    )


@pytest.mark.parametrize("argv", [["--timeout-ms", "soon"], ["--timeout-ms", "-5"], ["--timeout-ms"]])
def test_a_timeout_that_is_not_a_whole_number_is_invalid_args(tmp_path, argv):
    code, wire = invoke(["snapshot", "--settle", *argv], FakeHub([J7]), tmp_path)
    assert code == 2 and wire["error"]["code"] == "INVALID_ARGS"
