"""The JSON between `adapters/remote/wire.py` and `host/phone_host.py`. Each test runs the real
script and reads its answer with `wire.py`, so a key renamed on one side fails here."""

import shlex
import socket

import pytest
from host_support import EMULATOR_ROW, J7_ROW, FakeAdbServer, run_host

from agent_phone.adapters.remote.wire import (
    Busy,
    Grant,
    lease_words,
    list_words,
    parse_grant,
    parse_listing,
    release_words,
)
from agent_phone.core.device import Connected, Lease, Serial
from agent_phone.core.outcome import ErrorCode, Refusal

J7 = Serial("0a1b2c3d4e5f6a7b")
ADA, BEN = "5c0e11aa22bb33cc", "77dd88ee99ff0011"


def ask(state, adb, who, words):
    return run_host(state, adb.port, who, shlex.join(words))[1]


def test_a_grant_a_listing_and_a_refusal_read_as_core_types(tmp_path):
    adb = FakeAdbServer(J7_ROW, EMULATOR_ROW, "R58M1234567            unauthorized usb:1-1.3 transport_id:3")
    grant = parse_grant(ask(tmp_path, adb, "ada", lease_words(J7, ADA, "schedule reel 12", 120, 9008)), J7)
    assert isinstance(grant, Grant) and len(grant.tenure) == 8
    assert adb.forwards == {grant.host_port: (J7, 9008)}
    assert grant.lease == Lease("ada", "schedule reel 12", 0, 120, True)

    refused = parse_grant(ask(tmp_path, adb, "ben", lease_words(J7, BEN, "snapshot", 120, 9008)), J7)
    assert refused == Busy(Lease("ada", "schedule reel 12", 0, refused.lease.free_in_s, False))
    assert 118 <= refused.lease.free_in_s <= 120

    listing = parse_listing(ask(tmp_path, adb, "ben", list_words(BEN)))
    assert listing.adb_version == 41
    assert listing.phones == (
        Connected(J7, "SM_J730F", True, refused.lease),
        Connected(Serial("emulator-5554"), "sdk_gphone64_arm64", True),
        Connected(Serial("R58M1234567"), "", False),
    )
    assert parse_listing(ask(tmp_path, adb, "ada", list_words(ADA))).phones[0].lease.mine is True

    assert ask(tmp_path, adb, "ada", release_words(J7, ADA)) == {"v": 1, "ok": True}
    assert parse_listing(ask(tmp_path, adb, "ben", list_words(BEN))).phones[0].lease is None


@pytest.mark.parametrize("task", ["-rf", "it's a 'quoted' task", "two  spaces; and $(a) `b`", ""])
def test_a_task_reaches_the_host_as_the_caller_wrote_it(tmp_path, task):
    adb = FakeAdbServer(J7_ROW)
    grant = parse_grant(ask(tmp_path, adb, "ada", lease_words(J7, ADA, task, 120, 9008)), J7)
    assert isinstance(grant, Grant) and grant.lease.task == task


def test_a_phone_the_host_does_not_list_as_ready_is_no_device(tmp_path):
    adb = FakeAdbServer(EMULATOR_ROW)
    with pytest.raises(Refusal) as refused:
        parse_grant(ask(tmp_path, adb, "ada", lease_words(J7, ADA, "snapshot", 120, 9008)), J7)
    assert refused.value.code is ErrorCode.NO_DEVICE and refused.value.details == {"serial": J7}


def test_a_host_whose_adb_is_down_is_a_transport_refusal_with_the_hosts_words(tmp_path):
    with socket.socket() as unused:
        unused.bind(("127.0.0.1", 0))
        dead = unused.getsockname()[1]
    down = run_host(tmp_path, dead, "ada", shlex.join(list_words(ADA)))[1]
    with pytest.raises(Refusal) as refused:
        parse_listing(down)
    assert refused.value.code is ErrorCode.TRANSPORT and "adb server on this host" in refused.value.message
    down = run_host(tmp_path, dead, "ada", shlex.join(lease_words(J7, ADA, "snapshot", 120, 9008)))[1]
    with pytest.raises(Refusal) as refused:
        parse_grant(down, J7)
    assert refused.value.code is ErrorCode.TRANSPORT and "adb server on this host" in refused.value.message


@pytest.mark.parametrize(
    ("answer", "field"),
    [
        ({"v": 1, "phones": []}, "adb"),
        ({"v": 1, "adb": True, "phones": []}, "adb"),
        ({"v": 1, "adb": 41}, "phones"),
        ({"v": 1, "adb": 41, "phones": [{"serial": "s", "state": "device", "lease": None}]}, "model"),
        (
            {"v": 1, "adb": 41, "phones": [{"serial": "s", "model": "m", "state": "device", "lease": {}}]},
            "by",
        ),
    ],
)
def test_a_listing_of_another_shape_is_refused_and_names_the_field(answer, field):
    with pytest.raises(Refusal) as refused:
        parse_listing(answer)
    assert refused.value.code is ErrorCode.TRANSPORT and refused.value.details == {"field": field}


@pytest.mark.parametrize(
    ("answer", "field"),
    [
        ({"v": 1, "ok": True, "port": 41001, "lease": {}}, "id"),
        ({"v": 1, "ok": True, "id": "t1", "port": None, "lease": {}}, "port"),
        ({"v": 1, "ok": True, "id": "t1", "port": 41001}, "lease"),
        ({"v": 1, "ok": False, "error": "busy"}, "lease"),
    ],
)
def test_a_grant_of_another_shape_is_refused_and_names_the_field(answer, field):
    with pytest.raises(Refusal) as refused:
        parse_grant(answer, J7)
    assert refused.value.code is ErrorCode.TRANSPORT and refused.value.details == {"field": field}
