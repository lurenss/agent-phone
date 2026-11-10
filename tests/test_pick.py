"""`Snapshot.pick` over the lines a snapshot printed: a query names exactly one ref of that
snapshot, or the pick is refused. It reads no phone, so a consumer can choose between elements of
a screen it already holds."""

import pytest
from fakes import J7_BOOT, J7_SERIAL
from support import fixture_screen, snapshot_of

from agent_phone import Match, Q, Role
from agent_phone.core.device import DeviceIdentity
from agent_phone.core.outcome import ErrorCode, Refusal
from agent_phone.core.snapshot.snapshot import SnapshotId

DEVICE = DeviceIdentity(J7_SERIAL, J7_BOOT)


def snapshot(fixture):
    return snapshot_of(fixture_screen(fixture), SnapshotId("k3x9q"), DEVICE)


def test_pick_returns_the_one_ref_a_query_names():
    home = snapshot("mbs-home")
    assert str(home.pick(Q("Reel", role=Role.BUTTON))) == "@k3x9q:e8"
    assert home.pick(Q("create new", match=Match.PREFIX)) == home.ref(16)


def test_pick_matches_the_fields_a_line_prints():
    settings = snapshot("settings-home")
    assert settings.pick(Q(text="Ringtone")) == settings.ref(5)
    assert settings.pick(Q(text="Bluetooth")) == settings.ref(4), (
        "one value of a detail, as find --text reads it"
    )
    assert settings.pick(Q(text="notif", match=Match.PREFIX)) == settings.ref(6)
    assert settings.pick(Q(id="dashboard_container")) == settings.ref(3)
    assert settings.pick(Q(role=Role.LIST)) == settings.ref(3)


def test_several_matches_are_ambiguous_and_the_refusal_lists_their_refs():
    home = snapshot("mbs-home")
    with pytest.raises(Refusal) as refused:
        home.pick(Q("Home"))
    assert refused.value.code is ErrorCode.AMBIGUOUS_TARGET
    assert refused.value.details == {"matches": 2, "refs": ["@k3x9q:e2", "@k3x9q:e14"]}


def test_below_keeps_only_the_lines_after_the_first_line_that_matches_it():
    home = snapshot("mbs-home")
    assert home.pick(Q("Home"), below=Q("Welcome to Meta Business Suite")) == home.ref(14)


def test_no_match_is_not_found():
    home = snapshot("mbs-home")
    for query, below in ((Q("Nowhere"), None), (Q("Reel"), Q("More")), (Q("Reel"), Q("Nowhere"))):
        with pytest.raises(Refusal) as refused:
            home.pick(query, below=below)
        assert refused.value.code is ErrorCode.NOT_FOUND


def test_a_line_with_no_ref_is_never_picked():
    home = snapshot("mbs-home")
    with pytest.raises(Refusal) as refused:
        home.pick(Q("See more"))
    assert refused.value.code is ErrorCode.NOT_FOUND
