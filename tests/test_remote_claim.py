"""`Claim`: this computer's lease on one phone. The host is a `FakeLink`, the wait runs on a fake
clock, and the wall clock is moved by hand, which is how a laptop's sleep looks to a process."""

import stat

import pytest
from remote_support import FakeLink, Wall, busy, granted
from support import FakeClock

from agent_phone.adapters.remote.claim import RENEW_AFTER_S, TTL_S, Claim, holder_id
from agent_phone.adapters.uiautomator2.server import PUSH_TIMEOUT_S
from agent_phone.core.device import Serial
from agent_phone.core.outcome import ErrorCode, Refusal

J7 = Serial("0a1b2c3d4e5f6a7b")
LEASE = ("lease", J7, "--holder", "5c0e", "--task=snapshot", "--ttl", "120", "--port", "9008")
RELEASE = ("release", J7, "--holder", "5c0e")
UNREACHABLE = Refusal(ErrorCode.TRANSPORT, "ssh could not reach the phone host farm.")


def claim_on(link, *, linger=False, wait_s=0.0, clock=None, wall=None):
    return Claim(link, J7, "5c0e", "snapshot", 9008, linger, clock or FakeClock(), wait_s, wall or Wall())


def test_taking_a_free_phone_is_one_lease_call_and_one_forward_to_the_port_it_carries():
    link = FakeLink(granted(port=41873))
    claim = claim_on(link)
    with pytest.raises(Refusal) as early:
        _ = claim.local_port
    assert early.value.code is ErrorCode.INTERNAL
    claim.take()
    assert link.asked == [LEASE] and link.forwarded == [41873] and claim.local_port == 50001
    assert TTL_S == 120, "the lease the script is asked for"


def test_the_longest_call_of_the_backend_fits_between_a_renewal_and_the_deadline():
    assert TTL_S - RENEW_AFTER_S > PUSH_TIMEOUT_S, "a jar push that starts just before a renewal is due"


def test_taking_waits_for_another_holder_and_gets_the_phone_when_they_let_go():
    link, clock = FakeLink(busy(), busy(), granted()), FakeClock()
    claim = claim_on(link, wait_s=10.0, clock=clock)
    claim.take()
    assert link.asked == [LEASE] * 3 and clock.pauses == [1.0, 1.0] and claim.local_port == 50001


def test_a_phone_that_stays_held_is_device_busy_with_who_has_it_and_for_what():
    link, clock = FakeLink(busy(free_in_s=95), busy(free_in_s=85)), FakeClock()
    with pytest.raises(Refusal) as refused:
        claim_on(link, wait_s=10.0, clock=clock).take()
    assert refused.value.code is ErrorCode.DEVICE_BUSY
    assert refused.value.message == (
        "ben is driving 0a1b2c3d4e5f6a7b (schedule reel 12). The lease runs out in 85 s unless ben "
        "renews it. This command waited 10 s."
    )
    assert refused.value.details == {
        "serial": J7,
        "by": "ben",
        "task": "schedule reel 12",
        "free_in_s": 85,
        "waited_s": 10.0,
    }
    assert len(link.asked) == 11 and link.forwarded == [], "no port is made for a phone that was not leased"


def test_keeping_a_young_grant_costs_nothing_and_an_older_one_is_renewed_with_its_forwards():
    link, wall = FakeLink(granted()), Wall()
    claim = claim_on(link, wall=wall)
    claim.take()
    wall.time += RENEW_AFTER_S - 1
    claim.keep()
    assert link.asked == [LEASE] and link.refreshed == 0
    wall.time += 1
    claim.keep()
    claim.keep()
    assert link.asked == [LEASE] * 2 and link.refreshed == 1


def test_a_computer_that_slept_through_its_lease_keeps_the_phone_when_nobody_took_it():
    link, wall = FakeLink(granted("t1")), Wall()
    claim = claim_on(link, wall=wall)
    claim.take()
    wall.time += 3 * 3600
    claim.keep()
    assert link.asked == [LEASE] * 2 and link.refreshed == 1


def test_a_computer_that_slept_while_another_holder_had_the_phone_is_refused_from_then_on():
    link, wall = FakeLink(granted("t1"), granted("t2")), Wall()
    claim = claim_on(link, wall=wall)
    claim.take()
    wall.time += 3 * 3600
    for _ in range(2):
        with pytest.raises(Refusal) as refused:
            claim.keep()
        assert (
            refused.value.code is ErrorCode.DEVICE_BUSY
            and "another holder had the phone" in refused.value.message
        )
    assert link.asked == [LEASE] * 2 and link.refreshed == 0, "a lost claim asks the host no more"


def test_a_lease_another_holder_has_taken_is_refused_with_their_name():
    link, wall = FakeLink(granted(), busy(by="ben", task="publish")), Wall()
    claim = claim_on(link, wall=wall)
    claim.take()
    wall.time += 200
    with pytest.raises(Refusal) as refused:
        claim.keep()
    assert refused.value.code is ErrorCode.DEVICE_BUSY
    assert refused.value.details == {"serial": J7, "by": "ben", "task": "publish", "free_in_s": 95}


def test_a_host_that_moved_the_port_inside_one_tenure_is_a_transport_refusal():
    link, wall = FakeLink(granted("t1", port=41001), granted("t1", port=41002)), Wall()
    claim = claim_on(link, wall=wall)
    claim.take()
    wall.time += RENEW_AFTER_S
    for _ in range(2):
        with pytest.raises(Refusal) as refused:
            claim.keep()
        assert refused.value.code is ErrorCode.TRANSPORT
    assert len(link.asked) == 2


def test_a_host_that_cannot_be_reached_refuses_that_call_only():
    link, wall = FakeLink(granted(), UNREACHABLE, granted()), Wall()
    claim = claim_on(link, wall=wall)
    claim.take()
    wall.time += RENEW_AFTER_S
    with pytest.raises(Refusal) as refused:
        claim.keep()
    assert refused.value is UNREACHABLE
    claim.keep()
    assert len(link.asked) == 3 and link.refreshed == 1


def test_a_wall_clock_that_was_set_back_asks_the_host_again():
    link, wall = FakeLink(granted()), Wall()
    claim = claim_on(link, wall=wall)
    claim.take()
    wall.time -= 3600
    claim.keep()
    assert len(link.asked) == 2


def test_a_session_releases_its_lease_and_a_command_line_leaves_it_to_run_out():
    session = FakeLink(granted(), {"v": 1, "ok": True})
    claim = claim_on(session, linger=False)
    claim.take()
    claim.drop()
    claim.drop()
    assert session.asked == [LEASE, RELEASE]

    command = FakeLink(granted())
    claim = claim_on(command, linger=True)
    claim.take()
    claim.drop()
    assert command.asked == [LEASE]


def test_a_release_that_fails_and_a_claim_that_was_never_granted_cost_nothing_more():
    failing = FakeLink(granted(), UNREACHABLE)
    claim = claim_on(failing)
    claim.take()
    claim.drop()
    refused = FakeLink(busy())
    claim = claim_on(refused)
    with pytest.raises(Refusal):
        claim.take()
    claim.drop()
    assert refused.asked == [LEASE]


def test_the_holder_id_is_made_once_per_state_root_and_closed_to_other_users(tmp_path):
    root = tmp_path / "state"
    first = holder_id(root)
    assert len(first) == 16 and int(first, 16) >= 0
    assert holder_id(root) == first and holder_id(tmp_path / "another") != first
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    assert stat.S_IMODE((root / "remote").stat().st_mode) == 0o700
    assert [path.name for path in (root / "remote").iterdir()] == ["holder"]
