"""`remote_hub` over the real uiautomator2 hub. ssh is a fake that hands each request to the real
`host/phone_host.py`, the host's adb server is a fake, and so is this computer's adb client. What
a lease's port reaches is a small HTTP server that answers like the phone's."""

import shutil
import stat
from contextlib import contextmanager
from pathlib import Path

import pytest
from fakes import FakePhone, info_for
from host_support import EMULATOR_ROW, J7_ROW, FakeAdbServer
from remote_support import DeviceServer, FakeLink, FakeSsh, TunnelAdb, Wall, busy, granted
from support import FakeClock, fixture_screen

from agent_phone.adapters.remote import remote_hub
from agent_phone.adapters.remote.claim import Claim
from agent_phone.adapters.remote.hub import LeasedPhone, RemoteAdb
from agent_phone.adapters.uiautomator2.phone import U2Hub
from agent_phone.core.act.ledger import Ledger
from agent_phone.core.device import Lease, Serial
from agent_phone.core.outcome import ErrorCode, Refusal
from agent_phone.core.phone import Key, KeyName, NotSent, Sent
from agent_phone.core.policy.engine import Clear, ClearReason, Grant

J7 = Serial("0a1b2c3d4e5f6a7b")


@contextmanager
def hub_on(root, ssh, adb=None, *, linger=False, task="snapshot", make_hub=None):
    adb = adb or TunnelAdb()
    clock = FakeClock()
    with remote_hub(
        "farm",
        root,
        adb,
        make_hub or (lambda tunnel: U2Hub(tunnel, 900, clock)),
        device_port=9008,
        task=task,
        linger=linger,
        wait_s=0.0,
        clock=clock,
        run=ssh,
    ) as hub:
        yield hub


@pytest.fixture
def host(tmp_path):
    adb = FakeAdbServer(J7_ROW, EMULATOR_ROW)
    ssh = FakeSsh(tmp_path, adb)
    yield ssh, adb
    ssh.close()


def test_naming_a_phone_host_reaches_nothing_and_writes_nothing_until_a_phone_is_asked_for(short_root, host):
    ssh, _ = host
    local = TunnelAdb()
    with hub_on(short_root / "state", ssh, local):
        pass
    assert ssh.calls == [] and local.ran == [] and not (short_root / "state").exists()


def test_a_state_root_too_long_for_a_control_socket_is_refused_before_anything_is_written_there(host):
    ssh, _ = host
    root = Path("/tmp") / ("r" * 90)
    try:
        with hub_on(root, ssh) as hub:
            with pytest.raises(Refusal) as refused:
                hub.connected()
        assert refused.value.code is ErrorCode.INVALID_ARGS and ssh.calls == []
        assert not root.exists()
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_a_state_root_that_ssh_would_misread_is_refused_before_anything_is_written_there(short_root, host):
    ssh, _ = host
    with hub_on(short_root / "two words", ssh) as hub:
        with pytest.raises(Refusal) as refused:
            hub.connected()
    assert refused.value.code is ErrorCode.INVALID_ARGS and ssh.calls == []
    assert not (short_root / "two words").exists()


def test_the_devices_of_a_phone_host_say_who_holds_each_phone(short_root, host, tmp_path):
    ssh, host_adb = host
    with hub_on(short_root / "ben", FakeSsh(tmp_path, host_adb, "ben"), task="schedule reel 12") as bens:
        phone = bens.open(J7)
        with hub_on(short_root / "ada", ssh) as hub:
            held, free = hub.connected()
        assert held.serial == J7 and (held.model, held.ready) == ("SM_J730F", True)
        assert held.lease == Lease("ben", "schedule reel 12", 0, held.lease.free_in_s, False)
        assert (free.serial, free.ready, free.lease) == ("emulator-5554", True, None)
        assert stat.S_IMODE((short_root / "ada").stat().st_mode) == 0o700
        phone.close()


def test_a_phone_is_opened_read_and_closed_through_the_lease_and_no_forward_reaches_the_hosts_adb(
    short_root, host
):
    ssh, host_adb = host
    local = TunnelAdb()
    with hub_on(short_root, ssh, local) as hub:
        assert [device.serial for device in hub.connected()] == [J7, "emulator-5554"]
        phone = hub.open(J7)
        assert phone.read() == fixture_screen("settings-home") and phone.info().model == "SM-J730F"
        (lease_port,) = host_adb.forwards
        assert host_adb.forwards == {lease_port: (J7, 9008)}, "the script made the one port, for the lease"
        assert sorted(ssh.forwards.values()) == sorted([5037, lease_port])
        phone.close()
        assert host_adb.forwards == {}, "a session gives the phone back when it closes"
    assert ssh.forwards == {}, "leaving the hub cancels this process's forwards"

    assert local.ran[0] == ("version",), "the two adb versions are compared before the first command"
    (tunnel,) = {args[:4] for args in local.ran[1:]}
    assert tunnel[:3] == ("-H", "127.0.0.1", "-P") and tunnel[3].isdigit()
    assert local.sent and not any("forward" in args for args in local.sent), local.sent
    assert [request.split()[0] for request in ssh.requests] == ["list", "lease", "release"]


def test_a_command_line_leaves_its_lease_for_the_next_command_of_the_job(short_root, host):
    ssh, host_adb = host
    with hub_on(short_root, ssh, linger=True) as hub:
        hub.open(J7).close()
    assert len(host_adb.forwards) == 1
    with hub_on(short_root, ssh, linger=True) as hub:
        assert hub.connected()[0].lease.mine is True
        hub.open(J7).close()
    assert len(host_adb.forwards) == 1 and "release" not in " ".join(ssh.requests)


def test_a_second_state_root_is_refused_with_who_drives_the_phone_and_for_what(short_root, host):
    ssh, _ = host
    with (
        hub_on(short_root / "one", ssh, task="schedule reel 12") as first,
        hub_on(short_root / "two", ssh) as second,
    ):
        phone = first.open(J7)
        with pytest.raises(Refusal) as refused:
            second.open(J7)
        assert refused.value.code is ErrorCode.DEVICE_BUSY
        assert (refused.value.details["by"], refused.value.details["task"]) == ("ada", "schedule reel 12")
        phone.close()
        second.open(J7).close()


def test_an_adb_client_of_another_protocol_is_refused_before_it_can_kill_the_hosts_server(short_root, host):
    ssh, _ = host
    local = TunnelAdb(version="1.0.39")
    with hub_on(short_root, ssh, local) as hub:
        with pytest.raises(Refusal) as refused:
            hub.inspect(J7)
        assert refused.value.code is ErrorCode.TRANSPORT
        assert "protocol 39" in refused.value.message and "protocol 41" in refused.value.message
        with pytest.raises(Refusal):
            hub.open(J7)
    assert local.sent == [] and 5037 not in ssh.forwards.values()


def test_stopping_the_server_takes_the_lease_and_sends_the_hosts_adb_no_forward_command(short_root, host):
    ssh, host_adb = host
    local = TunnelAdb()
    with hub_on(short_root / "one", ssh, local) as hub, hub_on(short_root / "two", ssh) as other:
        assert hub.server(J7).status().running is True
        assert ssh.requests == [f"list --holder {(short_root / 'one/remote/holder').read_text().strip()}"]
        phone = other.open(J7)
        with pytest.raises(Refusal) as refused:
            hub.server(J7).stop()
        assert refused.value.code is ErrorCode.DEVICE_BUSY
        phone.close()
        hub.server(J7).stop()
        hub.server(J7).start()
    assert ("-s", J7, "push") in {args[:3] for args in local.sent}, "a stopped server is started with its jar"
    assert not any("forward" in args for args in local.sent), local.sent
    assert host_adb.forwards == {}


def test_a_backend_that_fails_to_open_gives_the_lease_back(short_root, host):
    ssh, host_adb = host

    class Broken:
        def open(self, serial, first_read=False):
            raise Refusal(ErrorCode.SERVER_UNAVAILABLE, "The server did not start.")

    with hub_on(short_root, ssh, make_hub=lambda tunnel: Broken()) as hub:
        with pytest.raises(Refusal) as refused:
            hub.open(J7)
    assert refused.value.code is ErrorCode.SERVER_UNAVAILABLE and host_adb.forwards == {}
    assert [request.split()[0] for request in ssh.requests] == ["lease", "release"]


def test_a_host_that_ssh_cannot_reach_is_a_transport_refusal(short_root, host):
    ssh, _ = host
    ssh.down = True
    with hub_on(short_root, ssh) as hub:
        with pytest.raises(Refusal) as refused:
            hub.connected()
    assert refused.value.code is ErrorCode.TRANSPORT and "Connection refused" in refused.value.message


def leased(link, wall):
    inner = FakePhone(info_for(J7), fixture_screen("settings-home"))
    claim = Claim(link, J7, "5c0e", "snapshot", 9008, False, FakeClock(), 0.0, wall)
    claim.take()
    return LeasedPhone(inner, claim, claim.drop), inner


def test_a_phone_that_keeps_its_lease_hands_on_the_permit_it_was_given_and_only_once(tmp_path):
    phone, inner = leased(FakeLink(granted("t1")), Wall())
    permit = Ledger(tmp_path, inner.info().identity).spend(
        Key(KeyName.BACK), Clear(ClearReason.NO_COMMIT_WORDS), Grant.none()
    )
    delivery = phone.inject(permit)
    assert len(inner.permits) == 1 and inner.permits[0] is permit
    assert isinstance(delivery, Sent), "the answer is the wrapped phone's"


def test_a_phone_whose_lease_was_lost_reads_nothing_and_sends_nothing(tmp_path):
    link, wall = FakeLink(granted("t1"), busy(by="ben", task="publish")), Wall()
    phone, inner = leased(link, wall)
    permit = Ledger(tmp_path, inner.info().identity).spend(
        Key(KeyName.BACK), Clear(ClearReason.NO_COMMIT_WORDS), Grant.none()
    )
    wall.time += 3600
    delivery = phone.inject(permit)
    assert (
        isinstance(delivery, NotSent) and delivery.code is ErrorCode.DEVICE_BUSY and "ben" in delivery.detail
    )
    for reach in (phone.read, phone.clipboard, phone.screenshot):
        with pytest.raises(Refusal) as refused:
            reach()
        assert refused.value.code is ErrorCode.DEVICE_BUSY
    assert inner.permits == [] and inner.reads == 0
    assert phone.info() == inner.info(), "the facts were read under the lease and are no call to the phone"
    phone.close()
    assert inner.closed


def test_a_forward_the_adapter_does_not_know_is_refused_and_never_sent():
    local = TunnelAdb()
    adb = RemoteAdb(local, lambda port: 50000, lambda serial: None, lambda: 41, 9008)
    for args in (
        ("-s", J7, "forward", "tcp:0", "tcp:7912"),
        ("forward", "tcp:8000", "tcp:9008"),
        ("forward",),
    ):
        with pytest.raises(Refusal) as refused:
            adb.run(args)
        assert refused.value.code is ErrorCode.INTERNAL
    assert (
        adb.run(("forward", "--list")).stdout == ""
        and adb.run(("-s", J7, "forward", "--remove", "tcp:1")).status == 0
    )
    assert local.ran == []
    assert DeviceServer.inputs == []


@pytest.mark.parametrize(
    "args",
    [
        ("kill-server",),
        ("start-server",),
        ("reconnect",),
        ("usb",),
        ("-s", J7, "tcpip", "5555"),
        ("-s", J7, "reboot"),
    ],
)
def test_an_adb_command_the_backend_never_sends_is_refused_and_does_not_reach_the_hosts_server(args):
    local = TunnelAdb()
    adb = RemoteAdb(local, lambda port: 50000, lambda serial: None, lambda: 41, 9008)
    with pytest.raises(Refusal) as refused:
        adb.run(args)
    assert refused.value.code is ErrorCode.INTERNAL and " ".join(args) in refused.value.message
    assert local.ran == []
