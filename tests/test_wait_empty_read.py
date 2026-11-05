"""A wait survives an empty read.

Between two screens Android can hand back a dump with no window on the default display, and the
backend raises `NO_SURFACE` for it. On the J7, Instagram's switch from the reel editor to the caption
screen did that 5.7 s into a 15 s `--wait-for`, and the command failed although the screen was on
a moment later. So inside a wait an empty read is a read on which no condition holds, and the wait
goes on reading until its deadline. `NO_SURFACE` ends a wait only when no read of it showed a screen.

Every test runs the command as an agent does, on a fake phone and a `FakeClock`, so a deadline is
measured on the clock and costs no real time.
"""

import pytest
from fakes import J7_SERIAL, FakeHub, invoke
from support import FakeClock, fixture_screen, node, screen_of, settled_from

from agent_phone.core.device import Connected
from agent_phone.core.outcome import ErrorCode, Refusal
from agent_phone.core.wait.clock import POLL_GAP_S
from agent_phone.core.wait.observe import SETTLE_DEADLINE_S

J7 = Connected(J7_SERIAL, "SM_J730F", ready=True)
EMPTY = Refusal(
    ErrorCode.NO_SURFACE, "The screen dump has no window on the default display. The screen may be off."
)
SETTINGS = fixture_screen("settings-home")
DISPLAY_TILE = 7


def page(*names):
    """A Settings window that shows each name as a line of text."""
    rows = [
        node("android.widget.TextView", text=name, bounds=f"[0,{i * 100}][1080,{i * 100 + 90}]")
        for i, name in enumerate(names)
    ]
    return screen_of(
        node("android.widget.FrameLayout", *rows, package="com.android.settings", bounds="[0,0][1080,1920]")
    )


def waited(tmp_path, screens, *flags):
    clock = FakeClock()
    hub = FakeHub([J7], screens=screens)
    code, wire = invoke(["wait", *flags], hub, tmp_path, clock=clock)
    return code, wire, hub.phones[0], clock


def ended_at(clock, phone, timeout_ms):
    """The wait stopped reading at its deadline and not before it."""
    assert timeout_ms / 1000 <= clock.time <= timeout_ms / 1000 + POLL_GAP_S
    assert phone.reads == len(clock.pauses) + 1
    assert phone.reads > 1


def test_a_for_that_sees_two_empty_reads_and_then_the_screen_holds(tmp_path):
    code, wire, phone, clock = waited(
        tmp_path, [EMPTY, EMPTY, page("Display", "Brightness")], "--for", "name=Brightness"
    )
    assert code == 0 and wire["ok"] is True
    assert wire["data"]["tree"] == ['text "Display" [0,0,1080,90]', 'text "Brightness" [0,100,1080,190]']
    assert phone.reads == 3 and clock.pauses == [POLL_GAP_S, POLL_GAP_S]


def test_an_input_whose_wait_for_sees_empty_reads_is_verified_when_the_screen_comes_back(tmp_path):
    code, wire = invoke(["snapshot"], FakeHub([J7], screens=[SETTINGS]), tmp_path)
    taken = wire["data"]["id"]
    after = page("Brightness")
    hub = FakeHub([J7], screens=[SETTINGS], after_input=[EMPTY, EMPTY, after])
    code, wire = invoke(
        ["click", f"@{taken}:e{DISPLAY_TILE}", "--wait-for", "name=Brightness"],
        hub,
        tmp_path,
        clock=FakeClock(),
    )
    assert code == 0 and wire["delivery"] == "delivered_verified"
    assert wire["data"]["verified_by"] == 'present name="Brightness"'
    assert wire["data"]["after"]["tree"] == ['text "Brightness" [0,0,1080,90]']


def test_a_gone_does_not_hold_on_an_empty_read(tmp_path):
    saving, saved = page("Saving", "Saved"), page("Saved")
    code, wire, phone, _ = waited(tmp_path, [EMPTY, saving, saved], "--gone", "name=Saving")
    assert code == 0 and wire["data"]["tree"] == ['text "Saved" [0,0,1080,90]']
    assert phone.reads == 3


def test_empty_reads_after_the_thing_was_last_seen_do_not_say_it_went(tmp_path):
    code, wire, phone, clock = waited(
        tmp_path, [page("Saving"), EMPTY], "--gone", "name=Saving", "--timeout-ms", "500"
    )
    assert code == 1 and wire["error"]["code"] == "TIMEOUT"
    assert wire["error"]["details"]["after"]["tree"] == ['text "Saving" [0,0,1080,90]']
    ended_at(clock, phone, 500)


@pytest.mark.parametrize(
    "flags",
    [
        ["--for", "name=Brightness"],
        ["--gone", "name=Brightness"],
        ["--app", "com.android.settings"],
        ["--settled"],
    ],
    ids=["for", "gone", "app", "settled"],
)
def test_a_wait_whose_every_read_is_empty_ends_no_surface_at_its_deadline(tmp_path, flags):
    code, wire, phone, clock = waited(tmp_path, [EMPTY], *flags, "--timeout-ms", "500")
    assert code == 1 and wire["error"]["code"] == "NO_SURFACE"
    assert wire["delivery"] == "not_delivered" and wire["retry"] == "safe"
    ended_at(clock, phone, 500)


def test_a_screen_and_then_empty_reads_to_the_deadline_is_a_timeout_with_that_screen(tmp_path):
    code, wire, phone, clock = waited(
        tmp_path, [SETTINGS, EMPTY], "--for", "name=Brightness", "--timeout-ms", "500"
    )
    assert code == 1 and wire["error"]["code"] == "TIMEOUT"
    shown = wire["error"]["details"]["after"]
    assert shown["app"] == "com.android.settings" and any(
        'button "Display"' in line for line in shown["tree"]
    )
    ended_at(clock, phone, 500)


def test_a_settled_wait_that_saw_only_one_screen_is_a_timeout_that_says_unsettled(tmp_path):
    code, wire, phone, clock = waited(tmp_path, [SETTINGS, EMPTY], "--settled", "--timeout-ms", "500")
    assert code == 1 and wire["error"]["code"] == "TIMEOUT"
    assert wire["error"]["details"]["after"]["settled"] == "unsettled"
    ended_at(clock, phone, 500)


def test_an_input_whose_wait_for_sees_a_screen_and_then_only_empty_reads_times_out_on_that_screen(tmp_path):
    _, wire = invoke(["snapshot"], FakeHub([J7], screens=[SETTINGS]), tmp_path)
    hub = FakeHub([J7], screens=[SETTINGS], after_input=[SETTINGS, EMPTY])
    code, wire = invoke(
        ["click", f"@{wire['data']['id']}:e{DISPLAY_TILE}", "--wait-for", "name=Brightness"],
        hub,
        tmp_path,
        clock=FakeClock(),
    )
    assert code == 1 and wire["error"]["code"] == "TIMEOUT" and wire["delivery"] == "delivered_unverified"
    assert wire["data"]["after"]["app"] == "com.android.settings"


def test_an_input_whose_wait_for_sees_only_empty_reads_ends_no_surface_at_its_deadline(tmp_path):
    _, wire = invoke(["snapshot"], FakeHub([J7], screens=[SETTINGS]), tmp_path)
    clock = FakeClock()
    hub = FakeHub([J7], screens=[SETTINGS], after_input=[EMPTY])
    code, wire = invoke(
        ["click", f"@{wire['data']['id']}:e{DISPLAY_TILE}", "--wait-for", "name=Brightness"]
        + ["--timeout-ms", "500"],
        hub,
        tmp_path,
        clock=clock,
    )
    assert code == 1 and wire["error"]["code"] == "NO_SURFACE" and wire["delivery"] == "delivered_unverified"
    assert wire["data"]["input"]["kind"] == "tap" and wire["data"]["after"] is None
    assert 0.5 <= clock.time <= 0.5 + 3 * POLL_GAP_S


def test_any_other_refusal_between_empty_reads_still_ends_the_wait_at_once(tmp_path):
    lost = Refusal(ErrorCode.TRANSPORT, "the server did not answer")
    code, wire, phone, clock = waited(tmp_path, [EMPTY, lost, SETTINGS], "--for", "name=Brightness")
    assert code == 1 and wire["error"]["code"] == "TRANSPORT"
    assert phone.reads == 2 and clock.pauses == [POLL_GAP_S]


def test_an_empty_read_between_two_equal_screens_starts_settling_again(tmp_path):
    hub, clock = FakeHub([J7], screens=[page("Wi-Fi"), EMPTY, page("Wi-Fi"), page("Wi-Fi")]), FakeClock()
    code, wire = invoke(["snapshot", "--settle"], hub, tmp_path, clock=clock)
    assert code == 0 and wire["data"]["settled"] == "settled" and settled_from(clock, 2)


def test_settling_that_begins_on_an_empty_read_settles_on_the_screen_that_follows(tmp_path):
    hub, clock = FakeHub([J7], screens=[EMPTY, page("Wi-Fi"), page("Wi-Fi")]), FakeClock()
    code, wire = invoke(["snapshot", "--settle"], hub, tmp_path, clock=clock)
    assert code == 0 and wire["data"]["settled"] == "settled" and settled_from(clock, 1)


def test_settling_on_a_screen_that_stays_empty_ends_no_surface_at_the_settle_deadline(tmp_path):
    clock = FakeClock()
    hub = FakeHub([J7], screens=[EMPTY])
    code, wire = invoke(["snapshot", "--settle"], hub, tmp_path, clock=clock)
    assert code == 1 and wire["error"]["code"] == "NO_SURFACE"
    assert SETTLE_DEADLINE_S <= clock.time <= SETTLE_DEADLINE_S + POLL_GAP_S


def test_a_snapshot_with_no_wait_is_still_no_surface_on_its_first_empty_read(tmp_path):
    clock = FakeClock()
    hub = FakeHub([J7], screens=[EMPTY, SETTINGS])
    code, wire = invoke(["snapshot"], hub, tmp_path, clock=clock)
    assert code == 1 and wire["error"]["code"] == "NO_SURFACE"
    assert hub.phones[0].reads == 1 and clock.pauses == []
