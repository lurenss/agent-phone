"""`host/phone_host.py`, the one script on the computer the phones are plugged into. The lease
policy is one function with no clock in it, so these tests give it the time. The script itself
runs as a process against a fake adb server, the way sshd runs it."""

import itertools
import json
import os
import socket
import stat
import subprocess
from argparse import Namespace
from functools import partial
from pathlib import Path

import pytest
from host_support import (
    BOOT,
    EMULATOR_ROW,
    J7_ROW,
    SCRIPT,
    FakeAdbServer,
    call_host,
    host_command,
    host_env,
    load_script,
    run_host,
)

J7 = "0a1b2c3d4e5f6a7b"
ADA, BEN = ("ada", "5c0e11aa22bb33cc"), ("ben", "77dd88ee99ff0011")


@pytest.fixture(scope="module")
def host():
    return load_script()


def lease(
    host, asker, record, now, *, task="schedule reel 12", ttl=120, port=9008, fresh="t-new", ready=True
):
    who, holder = asker
    request = Namespace(verb="lease", serial=J7, holder=holder, task=task, ttl=ttl, port=port, fresh=fresh)
    return host.decide(request, who, record, ready, now)


def release(host, asker, record):
    who, holder = asker
    return host.decide(Namespace(verb="release", serial=J7, holder=holder), who, record, False, 0.0)


def held_by_ada(host, port=41001):
    return {**lease(host, ADA, None, 100.0, fresh="t-ada").record, "port": port}


def test_a_free_phone_is_granted_and_the_next_holder_learns_who_has_it_and_for_what(host):
    first = lease(host, ADA, None, 100.0, fresh="t-ada")
    assert first.status == host.YES and first.body["id"] == "t-ada"
    assert first.body["lease"] == {
        "by": "ada",
        "task": "schedule reel 12",
        "held_s": 0,
        "free_in_s": 120,
        "mine": True,
    }
    held = held_by_ada(host)
    second = lease(host, BEN, held, 110.0)
    assert second.status == host.BUSY
    assert second.body == {
        "v": 1,
        "ok": False,
        "error": "busy",
        "lease": {"by": "ada", "task": "schedule reel 12", "held_s": 10, "free_in_s": 110, "mine": False},
    }
    assert second.record is held and second.port_to_close is None, "a refusal changes nothing"


def test_a_fresh_lease_has_all_its_seconds_left_whatever_the_clock_reads(host):
    """3486.4 + 900 - 3486.4 is 899.9999999999995 in floating point."""
    assert lease(host, ADA, None, 3486.4, ttl=900).body["lease"]["free_in_s"] == 900


def test_a_lease_nobody_renews_passes_to_the_next_asker_with_a_new_tenure_and_the_old_port_closed(host):
    taken = lease(host, BEN, held_by_ada(host), 220.0, fresh="t-ben")
    assert taken.status == host.YES and taken.body["id"] == "t-ben"
    assert taken.port_to_close == 41001 and taken.record["port"] is None, (
        "the old holder's port never carries on"
    )
    assert taken.record["since"] == 220.0 and taken.record["until"] == 340.0


def test_a_renewal_keeps_the_tenure_and_the_port_and_moves_the_deadline(host):
    renewed = lease(host, ADA, held_by_ada(host), 130.0, task="publish reel 12", ttl=900)
    assert renewed.body["id"] == "t-ada" and renewed.body["port"] == 41001 and renewed.port_to_close is None
    assert renewed.body["lease"]["held_s"] == 30 and renewed.body["lease"]["task"] == "publish reel 12"
    assert renewed.record["since"] == 100.0 and renewed.record["until"] == 1030.0


def test_a_holder_that_comes_back_late_keeps_its_tenure_when_nobody_took_the_phone(host):
    back = lease(host, ADA, held_by_ada(host), 500.0)
    assert back.body["id"] == "t-ada" and back.body["port"] == 41001 and back.body["lease"]["held_s"] == 400


def test_a_holder_that_comes_back_after_another_one_gets_a_new_tenure(host):
    bens = {**lease(host, BEN, held_by_ada(host), 220.0, fresh="t-ben").record, "port": 41002}
    freed = release(host, BEN, bens)
    assert freed.record is None and freed.port_to_close == 41002
    back = lease(host, ADA, freed.record, 230.0, fresh="t-ada-2")
    assert back.body["id"] == "t-ada-2", "a new id tells the client that another holder drove the phone"


def test_two_state_roots_of_one_person_are_two_holders(host):
    other_computer = ("ada", "0123456789abcdef")
    refused = lease(host, other_computer, held_by_ada(host), 110.0)
    assert refused.status == host.BUSY and refused.body["lease"]["mine"] is False


def test_only_the_holder_releases_and_a_release_can_run_twice(host):
    held = held_by_ada(host)
    by_ben = release(host, BEN, held)
    assert by_ben.status == host.YES and by_ben.record is held and by_ben.port_to_close is None
    by_ada = release(host, ADA, held)
    assert by_ada.body == {"v": 1, "ok": True} and by_ada.record is None and by_ada.port_to_close == 41001
    again = release(host, ADA, None)
    assert again.status == host.YES and again.record is None and again.port_to_close is None


def test_a_phone_that_adb_does_not_list_as_ready_is_not_leased(host):
    with pytest.raises(host.Refused) as refused:
        lease(host, ADA, None, 100.0, ready=False)
    assert refused.value.status == host.UNSERVED and refused.value.body["error"] == "no_device"


def test_asking_for_another_device_port_or_for_none_closes_the_port_the_lease_had(host):
    moved = lease(host, ADA, held_by_ada(host), 130.0, port=9009)
    assert (
        moved.port_to_close == 41001 and moved.record["port"] is None and moved.record["device_port"] == 9009
    )
    plain = lease(host, ADA, held_by_ada(host), 130.0, port=None)
    assert plain.port_to_close == 41001 and plain.body["port"] is None and plain.body["id"] == "t-ada"


def test_the_listing_shows_a_lease_while_it_is_in_time_and_says_which_one_is_the_askers(host):
    rows = [
        {"serial": J7, "model": "SM_J730F", "state": "device"},
        {"serial": "emulator-5554", "model": "sdk_gphone64_arm64", "state": "offline"},
    ]
    records = {J7: held_by_ada(host)}
    mine = host.listing(*ADA, records, rows, 41, 412.0 - 300)["phones"][0]["lease"]
    assert mine == {"by": "ada", "task": "schedule reel 12", "held_s": 12, "free_in_s": 108, "mine": True}
    theirs = host.listing(*BEN, records, rows, 41, 112.0)
    assert theirs["adb"] == 41 and theirs["phones"][0]["lease"]["mine"] is False
    assert theirs["phones"][1] == {**rows[1], "lease": None}
    assert host.listing(*BEN, records, rows, 41, 220.0)["phones"][0]["lease"] is None


def test_the_table_is_one_phone_per_line_for_a_person_to_read(host):
    rows = [
        {"serial": J7, "model": "SM_J730F", "state": "device"},
        {"serial": "emulator-5554", "model": "sdk_gphone64_arm64", "state": "device"},
        {"serial": "R58M1234567", "model": "", "state": "unauthorized"},
    ]
    record = {**held_by_ada(host), "who": "ben", "since": -187.0, "until": 220.0}
    assert host.table(host.listing(*ADA, {J7: record}, rows, 41, 125.0)) == (
        "0a1b2c3d4e5f6a7b  SM_J730F            busy  ben: schedule reel 12 (5 min, free in 95 s)\n"
        "emulator-5554     sdk_gphone64_arm64  free\n"
        "R58M1234567                           unauthorized\n"
    )
    assert host.table(host.listing(*ADA, {}, [], 41, 0.0)) == "adb lists no phone.\n"


@pytest.mark.parametrize(
    "words",
    [
        "lease",
        "lease 0a1b2c3d4e5f6a7b",
        "lease ../x --holder h",
        "lease 0a1b2c3d4e5f6a7b --holder 'a b'",
        "lease 0a1b2c3d4e5f6a7b --holder h --ttl 5",
        "lease 0a1b2c3d4e5f6a7b --holder h --ttl 1e3",
        "lease 0a1b2c3d4e5f6a7b --holder h --port 0",
        "lease 0a1b2c3d4e5f6a7b --holder h --port 99999",
        "release 0a1b2c3d4e5f6a7b",
        "list --holder ../x",
        "frobnicate",
        "--who mallory list",
        "sh -c id",
    ],
)
def test_a_request_the_script_cannot_read_is_a_usage_refusal(host, words):
    with pytest.raises(host.Refused) as refused:
        host.parse_request(words.split())
    assert refused.value.status == host.UNSERVED and refused.value.body["error"] == "usage"


def test_a_task_keeps_its_spaces_and_loses_what_does_not_print(host):
    request = host.parse_request(
        ["lease", J7, "--holder", "h", "--task", "schedule reel\x1b[2J 17:00" + "x" * 90]
    )
    assert request.task.startswith("schedule reel[2J 17:00x") and len(request.task) == host.TASK_CHARS


def test_a_record_from_another_boot_or_one_that_does_not_parse_is_no_record(host, tmp_path):
    record = {**held_by_ada(host), "boot": "boot-1"}
    host.write_record(str(tmp_path), J7, record)
    assert host.read_record(str(tmp_path), J7, "boot-1") == record
    assert host.read_record(str(tmp_path), J7, "boot-2") is None, (
        "its deadline is from a clock that restarted"
    )
    assert stat.S_IMODE((tmp_path / f"{J7}.json").stat().st_mode) == 0o600
    (tmp_path / f"{J7}.json").write_text('{"who": "ada"')
    assert host.read_record(str(tmp_path), J7, "boot-1") is None
    host.write_record(str(tmp_path), J7, None)
    host.write_record(str(tmp_path), J7, None)
    assert not (tmp_path / f"{J7}.json").exists()


def test_two_holders_use_the_script_end_to_end(tmp_path):
    adb = FakeAdbServer(J7_ROW, EMULATOR_ROW)
    words = f"lease {J7} --holder {ADA[1]} --task 'schedule reel 12' --port 9008"
    code, granted = run_host(tmp_path, adb.port, "ada", words)
    assert code == 0 and granted["ok"] and granted["lease"]["by"] == "ada"
    assert adb.forwards == {granted["port"]: (J7, 9008)}

    code, refused = run_host(tmp_path, adb.port, "ben", f"lease {J7} --holder {BEN[1]} --port 9008")
    assert code == 1 and refused["error"] == "busy" and refused["lease"]["task"] == "schedule reel 12"
    assert adb.forwards == {granted["port"]: (J7, 9008)}, "a refused holder gets no port"

    code, listed = run_host(tmp_path, adb.port, "ben", f"list --holder {BEN[1]}")
    assert code == 0 and listed["adb"] == 41
    assert [(row["serial"], row["model"], row["state"]) for row in listed["phones"]] == [
        (J7, "SM_J730F", "device"),
        ("emulator-5554", "sdk_gphone64_arm64", "device"),
    ]
    assert listed["phones"][0]["lease"]["by"] == "ada" and listed["phones"][1]["lease"] is None

    code, text = run_host(tmp_path, adb.port, "ben", None)
    assert code == 0 and text.splitlines()[0].startswith(
        f"{J7}  SM_J730F            busy  ada: schedule reel 12 ("
    )
    assert text.splitlines()[1] == "emulator-5554     sdk_gphone64_arm64  free"

    assert run_host(tmp_path, adb.port, "ben", f"release {J7} --holder {BEN[1]}") == (0, {"v": 1, "ok": True})
    assert adb.forwards == {granted["port"]: (J7, 9008)}, "only the holder's release frees the phone"
    assert run_host(tmp_path, adb.port, "ada", f"release {J7} --holder {ADA[1]}") == (0, {"v": 1, "ok": True})
    assert adb.forwards == {}, "the port goes with the lease"
    code, taken = run_host(tmp_path, adb.port, "ben", f"lease {J7} --holder {BEN[1]} --port 9008")
    assert code == 0 and taken["id"] != granted["id"] and adb.forwards == {taken["port"]: (J7, 9008)}

    state = tmp_path / "phone-host"
    assert stat.S_IMODE(state.stat().st_mode) == 0o700
    assert stat.S_IMODE((state / f"{J7}.json").stat().st_mode) == 0o600
    services = {
        request.split(":")[2] if request.startswith("host-serial") else request for request in adb.requests
    }
    assert services == {"host:devices-l", "host:version", "host:list-forward", "forward", "killforward"}


def test_a_renewal_keeps_its_port_gets_it_back_when_adb_forgot_it_and_a_new_one_when_it_is_gone(tmp_path):
    adb = FakeAdbServer(J7_ROW)
    words = f"lease {J7} --holder {ADA[1]} --port 9008"
    first = run_host(tmp_path, adb.port, "ada", words)[1]
    again = run_host(tmp_path, adb.port, "ada", words)[1]
    assert again["port"] == first["port"] and again["id"] == first["id"]
    assert adb.forwards == {first["port"]: (J7, 9008)}

    adb.forwards.clear()
    back = run_host(tmp_path, adb.port, "ada", words)[1]
    assert back["port"] == first["port"], "nobody has the number since"
    assert adb.forwards == {first["port"]: (J7, 9008)}

    adb.forwards.clear()
    adb.taken.add(first["port"])
    moved = run_host(tmp_path, adb.port, "ada", words)[1]
    assert moved["port"] != first["port"] and moved["id"] == first["id"], (
        "the client sees a new port in the same tenure"
    )
    assert adb.forwards == {moved["port"]: (J7, 9008)}


EMULATOR = "emulator-5554"


def with_port(serial, holder):
    return f"lease {serial} --holder {holder} --port 9008"


def asked(host, state, adb, asker, serial, now=None):
    """One lease with a port, in this process, where a test can say which port numbers are free."""
    who, holder = asker
    status, said = call_host(host, state, adb.port, who, with_port(serial, holder), now=now)
    return status, json.loads(said)


def offer(monkeypatch, host, adb, first):
    """`first` and the numbers after it are the ports that the kernel calls free next, and that an
    adb server hands out next. Neither knows that the record of a lease may still hold one."""
    adb.next_port = first
    monkeypatch.setattr(host, "free_port", itertools.count(first).__next__)


def test_after_adb_started_again_no_port_number_reaches_the_phone_of_another_lease(
    host, tmp_path, monkeypatch
):
    adb = FakeAdbServer(J7_ROW, EMULATOR_ROW)
    _, ada = asked(host, tmp_path, adb, ADA, J7)
    adb.forwards.clear()
    offer(monkeypatch, host, adb, ada["port"])

    _, ben = asked(host, tmp_path, adb, BEN, EMULATOR)
    assert ben["port"] != ada["port"]
    assert (ada["port"], EMULATOR) not in adb.bound, "ada's computer still points at her number"
    _, again = asked(host, tmp_path, adb, ADA, J7)
    assert again["id"] == ada["id"] and again["port"] == ada["port"]
    assert adb.forwards == {ada["port"]: (J7, 9008), ben["port"]: (EMULATOR, 9008)}


def test_a_renewal_never_takes_a_port_that_adb_now_holds_for_another_phone(tmp_path):
    adb = FakeAdbServer(J7_ROW, EMULATOR_ROW)
    ada = run_host(tmp_path, adb.port, "ada", with_port(J7, ADA[1]))[1]
    adb.forwards = {ada["port"]: (EMULATOR, 9008)}
    again = run_host(tmp_path, adb.port, "ada", with_port(J7, ADA[1]))[1]
    assert again["id"] == ada["id"] and again["port"] != ada["port"], "the grant carries the new port"
    assert adb.forwards == {ada["port"]: (EMULATOR, 9008), again["port"]: (J7, 9008)}


def test_a_release_leaves_a_port_that_adb_now_holds_for_another_phone(tmp_path):
    adb = FakeAdbServer(J7_ROW, EMULATOR_ROW)
    port = run_host(tmp_path, adb.port, "ada", with_port(J7, ADA[1]))[1]["port"]
    adb.forwards = {port: (EMULATOR, 9008)}
    assert run_host(tmp_path, adb.port, "ada", f"release {J7} --holder {ADA[1]}") == (0, {"v": 1, "ok": True})
    assert adb.forwards == {port: (EMULATOR, 9008)}


def test_a_takeover_never_opens_the_port_number_that_the_old_holder_still_points_at(
    host, tmp_path, monkeypatch
):
    adb = FakeAdbServer(J7_ROW)
    _, ada = asked(host, tmp_path, adb, ADA, J7, now=1000.0)
    offer(monkeypatch, host, adb, ada["port"])
    status, ben = asked(host, tmp_path, adb, BEN, J7, now=1120.0)
    assert status == 0 and ben["port"] != ada["port"] and adb.forwards == {ben["port"]: (J7, 9008)}
    assert adb.bound.count((ada["port"], J7)) == 1, "only ada's own lease ever opened her number"


def test_a_port_that_another_process_holds_is_refused_by_adb_and_the_lease_gets_the_next(
    host, tmp_path, monkeypatch
):
    adb = FakeAdbServer(J7_ROW)
    offer(monkeypatch, host, adb, 41001)
    adb.taken.add(41001)
    status, granted = asked(host, tmp_path, adb, ADA, J7)
    assert status == 0 and granted["port"] == 41002 and adb.forwards == {41002: (J7, 9008)}


def test_a_host_where_adb_opens_no_port_refuses_the_lease_and_the_phone_stays_free(
    host, tmp_path, monkeypatch
):
    adb = FakeAdbServer(J7_ROW)
    monkeypatch.setattr(host, "free_port", lambda: 41001)
    adb.taken.add(41001)
    status, refused = asked(host, tmp_path, adb, ADA, J7)
    assert status == 2 and refused["error"] == "host" and J7 in refused["message"]
    assert "Address already in use" in refused["message"], "adb's own reason is in the refusal"
    assert adb.forwards == {} and not (tmp_path / "phone-host" / f"{J7}.json").exists()


def test_an_adb_server_that_stops_answering_while_a_port_is_opened_is_adb_down_at_once(host):
    with socket.socket() as unused:
        unused.bind(("127.0.0.1", 0))
        dead = unused.getsockname()[1]
    with pytest.raises(host.Refused) as refused:
        host.open_port(J7, 0, 9008, set(), dead)
    assert refused.value.body["error"] == "adb_down", "not eight tries that each wait for adb"


def plant_socket(path):
    """What `ssh -R <path>:127.0.0.1:9` leaves on the host with a key's options (R1-15)."""
    with socket.socket(socket.AF_UNIX) as planted:
        planted.bind(str(path))


def test_nothing_that_a_key_or_an_older_script_left_in_the_state_folder_stops_a_lease(short_root):
    """The script locks the folder itself, so no path inside it has to be free. A key can leave a
    socket at any free path (R1-15), and the first script kept a file `lock` there."""
    adb = FakeAdbServer(J7_ROW)
    for left, plant in (("socket", plant_socket), ("file", Path.touch)):
        (short_root / left / "phone-host").mkdir(parents=True)
        plant(short_root / left / "phone-host" / "lock")
        code, granted = run_host(short_root / left, adb.port, "ada", with_port(J7, ADA[1]))
        assert code == 0 and granted["lease"]["by"] == "ada", left
        code, listed = run_host(short_root / left, adb.port, "ben", "list")
        assert [(row["serial"], row["lease"]["by"]) for row in listed["phones"]] == [(J7, "ada")]
        freed = run_host(short_root / left, adb.port, "ada", f"release {J7} --holder {ADA[1]}")
        assert freed == (0, {"v": 1, "ok": True}) and adb.forwards == {}


def test_a_socket_where_the_state_folder_should_be_refuses_each_request_and_names_the_path(short_root):
    adb = FakeAdbServer(J7_ROW)
    plant_socket(short_root / "phone-host")
    for words in (with_port(J7, ADA[1]), "list", f"release {J7} --holder {ADA[1]}"):
        code, refused = run_host(short_root, adb.port, "ada", words)
        assert code == 2 and refused["error"] == "host" and f"{short_root}/phone-host" in refused["message"]
    assert adb.forwards == {}


def test_a_socket_in_the_way_of_a_record_is_replaced_by_the_record(short_root):
    adb = FakeAdbServer(J7_ROW)
    (short_root / "phone-host").mkdir()
    plant_socket(short_root / "phone-host" / f"{J7}.json")
    plant_socket(short_root / "phone-host" / f"{J7}.json.tmp")
    code, granted = run_host(short_root, adb.port, "ada", with_port(J7, ADA[1]))
    assert code == 0 and adb.forwards == {granted["port"]: (J7, 9008)}
    assert run_host(short_root, adb.port, "ben", with_port(J7, BEN[1]))[0] == 1, "the record is there"


def test_a_record_that_cannot_be_read_refuses_the_request_and_never_frees_the_phone(tmp_path):
    adb = FakeAdbServer(J7_ROW, EMULATOR_ROW)
    held = run_host(tmp_path, adb.port, "ada", with_port(J7, ADA[1]))[1]
    record = tmp_path / "phone-host" / f"{J7}.json"
    record.chmod(0)
    for words in (with_port(J7, BEN[1]), with_port(EMULATOR, BEN[1]), "list"):
        code, refused = run_host(tmp_path, adb.port, "ben", words)
        assert code == 2 and refused["error"] == "host" and str(record) in refused["message"], words
    assert adb.forwards == {held["port"]: (J7, 9008)}, "ada still has her phone and her port"
    record.chmod(0o600)
    assert run_host(tmp_path, adb.port, "ben", with_port(J7, BEN[1]))[0] == 1


def test_a_link_where_a_record_should_be_is_not_followed(host, tmp_path):
    adb = FakeAdbServer(J7_ROW)
    (tmp_path / "phone-host").mkdir()
    elsewhere, link = tmp_path / "elsewhere.json", tmp_path / "phone-host" / f"{J7}.json"
    record = {**held_by_ada(host), "who": "mallory", "until": 9999.0, "boot": BOOT}
    elsewhere.write_text(json.dumps(record))
    link.symlink_to(elsewhere)
    status, said = call_host(host, tmp_path, adb.port, "ben", with_port(J7, BEN[1]), now=200.0)
    assert status == 0 and json.loads(said)["lease"]["by"] == "ben"
    assert json.loads(elsewhere.read_text()) == record and not link.is_symlink()


def test_a_person_leases_by_hand_with_no_port_and_the_admin_asks_from_a_shell_on_the_host(tmp_path):
    adb = FakeAdbServer(J7_ROW)
    by_hand = f"lease {J7} --holder by-hand --task 'manual check' --ttl 900"
    code, granted = run_host(tmp_path, adb.port, "ada", by_hand)
    assert code == 0 and granted["port"] is None and granted["lease"]["free_in_s"] == 900
    assert adb.forwards == {}
    code, listed = run_host(tmp_path, adb.port, "admin", None, "list")
    assert code == 0 and listed["phones"][0]["lease"]["task"] == "manual check"


def test_a_phone_that_is_unplugged_or_unauthorized_is_listed_and_not_leased(tmp_path):
    adb = FakeAdbServer("R58M1234567            unauthorized usb:1-1.3 transport_id:3")
    code, listed = run_host(tmp_path, adb.port, "ada", "list")
    assert listed["phones"] == [
        {"serial": "R58M1234567", "model": "", "state": "unauthorized", "lease": None}
    ]
    for serial in ("R58M1234567", J7):
        code, refused = run_host(tmp_path, adb.port, "ada", f"lease {serial} --holder h --port 9008")
        assert code == 2 and refused["error"] == "no_device" and serial in refused["message"]
    assert not any("forward" in request for request in adb.requests)


def test_with_adb_down_nothing_is_leased_and_a_release_still_frees_the_phone(tmp_path):
    adb = FakeAdbServer(J7_ROW)
    run_host(tmp_path, adb.port, "ada", f"lease {J7} --holder {ADA[1]} --port 9008")
    with socket.socket() as unused:
        unused.bind(("127.0.0.1", 0))
        dead = unused.getsockname()[1]
    for words in ("list", f"lease {J7} --holder {BEN[1]} --port 9008"):
        code, refused = run_host(tmp_path, dead, "ben", words)
        assert code == 2 and refused["ok"] is False and refused["error"] == "adb_down"
    assert run_host(tmp_path, dead, "ada", f"release {J7} --holder {ADA[1]}") == (0, {"v": 1, "ok": True})
    assert not (tmp_path / "phone-host" / f"{J7}.json").exists()


@pytest.mark.skipif(os.path.exists("/proc/sys/kernel/random/boot_id"), reason="this computer has a boot id")
def test_the_script_as_installed_serves_nothing_where_no_boot_id_can_be_read(tmp_path):
    adb = FakeAdbServer(J7_ROW)
    for words in ("list", f"lease {J7} --holder h --port 9008"):
        code, refused = run_host(tmp_path, adb.port, "ada", words, as_installed=True)
        assert code == 2 and refused["error"] == "host" and "boot_id" in refused["message"]
    assert adb.forwards == {} and not (tmp_path / "phone-host" / f"{J7}.json").exists()


def test_the_boot_id_is_the_text_of_its_file_and_a_host_without_one_serves_nothing(host, tmp_path, capsys):
    (tmp_path / "boot_id").write_text("0b5cf2a1-boot\n")
    assert host.boot_id(str(tmp_path / "boot_id")) == "0b5cf2a1-boot"
    (tmp_path / "empty").write_text("\n")
    adb = FakeAdbServer(J7_ROW)
    env = host_env(tmp_path, adb.port, with_port(J7, ADA[1]))
    for unreadable in ("empty", "missing"):
        boot = partial(host.boot_id, str(tmp_path / unreadable))
        assert host.main(["--who", "ada"], env, clock=lambda: 0.0, boot=boot) == host.UNSERVED
        assert '"error":"host"' in capsys.readouterr().out and adb.forwards == {}


def test_a_lease_ends_at_its_deadline_and_at_a_restart_of_the_host(host, tmp_path):
    adb = FakeAdbServer(J7_ROW)

    def lease_at(who, holder, now, boot="boot-1"):
        words = f"lease {J7} --holder {holder} --port 9008"
        status, said = call_host(host, tmp_path, adb.port, who, words, now=now, boot=boot)
        return status, json.loads(said)

    first = lease_at(*ADA, 1000.0)[1]
    status, refused = lease_at(*BEN, 1119.0)
    assert status == 1 and refused["lease"]["free_in_s"] == 1
    status, taken = lease_at(*BEN, 1120.0)
    assert status == 0 and taken["port"] != first["port"] and adb.forwards == {taken["port"]: (J7, 9008)}
    status, after_restart = lease_at(*ADA, 5.0, boot="boot-2")
    assert status == 0 and after_restart["id"] != taken["id"], (
        "the clock started again, so the record is void"
    )


def test_two_holders_that_ask_at_the_same_moment_get_one_grant(tmp_path):
    adb = FakeAdbServer(J7_ROW)
    run_host(tmp_path, adb.port, "ada", "list")
    asked = [
        subprocess.Popen(
            host_command(f"p{n}"),
            env=host_env(tmp_path, adb.port, f"lease {J7} --holder h{n} --port 9008"),
            stdout=subprocess.PIPE,
        )
        for n in range(8)
    ]
    codes = sorted(process.wait(timeout=20) for process in asked)
    for process in asked:
        process.stdout.close()
    assert codes == [0, 1, 1, 1, 1, 1, 1, 1] and len(adb.forwards) == 1


def test_the_callers_words_are_data_and_never_choose_who_asks(tmp_path):
    adb = FakeAdbServer(J7_ROW)
    for words in (f"lease {J7} --holder h; id", "--who mallory list", "sh -c id", "lease 'x"):
        code, refused = run_host(tmp_path, adb.port, "ada", words)
        assert code == 2 and refused["error"] == "usage", words
    code, granted = run_host(tmp_path, adb.port, "ada", f"lease {J7} --holder h --task '$(id); rm -rf /'")
    assert code == 0 and granted["lease"] == {**granted["lease"], "by": "ada", "task": "$(id); rm -rf /"}


def test_the_script_prints_the_authorized_keys_options_for_a_name(host, capsys):
    assert host.main(["key", "ada"], {}) == 0
    assert capsys.readouterr().out == (
        f'command="{SCRIPT} --who ada",restrict,port-forwarding,'
        'permitopen="127.0.0.1:*",permitlisten="127.0.0.1:1"\n'
    )
    for argv in (["key", 'ada",no-restrict'], ["key"], [], ["list"], ["--who", "Ada Lovelace"]):
        assert host.main(argv, {}) == 2
        assert '"error":"usage"' in capsys.readouterr().out
