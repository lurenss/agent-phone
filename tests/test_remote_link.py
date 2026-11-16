"""`Link`: one ssh alias through a connection OpenSSH shares. `ssh` is a fake here. What the real
one does with these arguments is measured in `probes/remote/FINDINGS.md`, area 1."""

import os
import stat
from pathlib import Path

import pytest

from agent_phone.adapters.remote import link as link_module
from agent_phone.adapters.remote.link import SOCKET_PATH_LIMIT, Done, Link, run_ssh
from agent_phone.core.outcome import ErrorCode, Refusal

LIST = '{"v":1,"adb":41,"phones":[]}\n'


class Ssh:
    def __init__(self, *answers: Done) -> None:
        self.answers = list(answers)
        self.ran: list[list[str]] = []

    def __call__(self, argv, timeout_s) -> Done:
        self.ran.append(list(argv))
        return self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]


def options(argv):
    return [argv[at + 1] for at, word in enumerate(argv) if word == "-o"]


def test_a_request_is_one_ssh_call_over_the_shared_connection_with_its_words_as_one_argument(short_root):
    ssh = Ssh(Done(0, LIST, ""))
    answer = Link("farm", short_root, ssh).ask(("lease", "0a1b2c3d4e5f6a7b", "--task=it's two words"))
    assert answer == {"v": 1, "adb": 41, "phones": []}
    (argv,) = ssh.ran
    assert argv[0] == "ssh" and argv[-3:] == [
        "--",
        "farm",
        "lease 0a1b2c3d4e5f6a7b '--task=it'\"'\"'s two words'",
    ]
    assert options(argv) == [
        "BatchMode=yes",
        "ControlMaster=auto",
        "ControlPersist=600",
        "ServerAliveInterval=15",
        "ServerAliveCountMax=3",
        "ConnectTimeout=10",
        f"ControlPath={short_root}/remote/farm.sock",
    ]
    assert stat.S_IMODE((short_root / "remote").stat().st_mode) == 0o700


def test_an_answer_that_says_no_is_still_an_answer(short_root):
    busy = '{"v":1,"ok":false,"error":"busy","lease":{}}\n'
    assert Link("farm", short_root, Ssh(Done(1, busy, ""))).ask(("lease",))["error"] == "busy"


@pytest.mark.parametrize(
    ("done", "said"),
    [
        (
            Done(255, "", "Warning: x\nssh: connect to host 192.0.2.1 port 22: Operation timed out\n"),
            "timed out",
        ),
        (Done(255, "", ""), "ssh gave no reason"),
        (Done(0, "Welcome to the host\n", ""), "Welcome to the host"),
        (Done(0, '{"v":2,"adb":41,"phones":[]}\n', ""), "version 1"),
        (Done(0, "[1]\n", ""), "version 1"),
        (Done(127, "", "sh: phone-host: not found\n"), "phone-host: not found"),
    ],
)
def test_ssh_that_fails_and_a_host_that_answers_something_else_are_transport_refusals(short_root, done, said):
    with pytest.raises(Refusal) as refused:
        Link("farm", short_root, Ssh(done)).ask(("list",))
    assert refused.value.code is ErrorCode.TRANSPORT
    assert said in refused.value.message and "farm" in refused.value.message


def test_a_forward_is_a_free_local_port_that_ssh_points_at_the_hosts_loopback(short_root):
    ssh = Ssh(Done(0, "", ""))
    link = Link("farm", short_root, ssh)
    local = link.forward(41001)
    (argv,) = ssh.ran
    assert argv[-6:] == ["-O", "forward", "-L", f"127.0.0.1:{local}:127.0.0.1:41001", "--", "farm"]
    assert f"ControlPath={short_root}/remote/farm.sock" in options(argv)


def test_a_local_port_that_was_taken_meanwhile_is_tried_again_with_another(short_root):
    ssh = Ssh(Done(255, "", "mux_client_forward: forwarding request failed\n"), Done(0, "", ""))
    local = Link("farm", short_root, ssh).forward(41001)
    asked = [argv[-3].split(":")[1] for argv in ssh.ran]
    assert len(asked) == 2 and asked[0] != asked[1] and asked[1] == str(local)

    never = Ssh(Done(255, "", "Control socket connect: No such file or directory\n"))
    with pytest.raises(Refusal) as refused:
        Link("farm", short_root, never).forward(41001)
    assert refused.value.code is ErrorCode.TRANSPORT and len(never.ran) == 3


def test_refresh_asks_for_each_forward_again_and_close_cancels_them(short_root):
    ssh = Ssh(Done(0, "", ""))
    link = Link("farm", short_root, ssh)
    specs = [f"127.0.0.1:{link.forward(port)}:127.0.0.1:{port}" for port in (5037, 41001)]
    ssh.ran.clear()
    link.refresh()
    assert [(argv[-5], argv[-3]) for argv in ssh.ran] == [("forward", spec) for spec in specs]
    ssh.ran.clear()
    link.close()
    link.close()
    assert [(argv[-5], argv[-3]) for argv in ssh.ran] == [("cancel", spec) for spec in specs]


def test_a_forward_that_cannot_be_made_again_is_a_transport_refusal(short_root):
    ssh = Ssh(Done(0, "", ""), Done(255, "", "bind: Address already in use\n"))
    link = Link("farm", short_root, ssh)
    link.forward(41001)
    with pytest.raises(Refusal) as refused:
        link.refresh()
    assert refused.value.code is ErrorCode.TRANSPORT
    link.close()


def test_a_state_root_too_long_for_a_control_socket_is_refused_before_ssh_runs():
    ssh = Ssh(Done(0, LIST, ""))
    root = Path("/tmp") / ("r" * (SOCKET_PATH_LIMIT - len("/tmp//remote/farm.sock") + 1))
    with pytest.raises(Refusal) as refused:
        Link("farm", root, ssh).ask(("list",))
    assert refused.value.code is ErrorCode.INVALID_ARGS and "AGENT_PHONE_HOME" in refused.value.message
    assert ssh.ran == [] and not root.exists()


@pytest.mark.parametrize(
    "folder", ["Application Support", "tab\there", "100%", 'a"b', "it's", "a\\b", "${HOME}"]
)
def test_a_state_root_that_ssh_would_read_as_something_else_is_refused_before_ssh_runs(short_root, folder):
    ssh = Ssh(Done(0, LIST, ""))
    with pytest.raises(Refusal) as refused:
        Link("farm", short_root / folder, ssh).ask(("list",))
    assert refused.value.code is ErrorCode.INVALID_ARGS and "AGENT_PHONE_HOME" in refused.value.message
    assert ssh.ran == [] and not (short_root / folder).exists()


@pytest.mark.parametrize("root", ["~/ap", "ap", "./ap"])
def test_a_state_root_that_is_not_an_absolute_path_is_refused_before_ssh_runs(tmp_path, monkeypatch, root):
    """Nothing expands the `~` of a variable set in a launchd plist or a `.env` file. ssh reads it
    as the home folder and agent-phone as a folder named `~`, so the two would not meet."""
    monkeypatch.chdir(tmp_path)
    ssh = Ssh(Done(0, LIST, ""))
    with pytest.raises(Refusal) as refused:
        Link("farm", Path(root), ssh).ask(("list",))
    assert refused.value.code is ErrorCode.INVALID_ARGS and "AGENT_PHONE_HOME" in refused.value.message
    assert ssh.ran == [] and list(tmp_path.iterdir()) == []


def test_an_ask_that_hangs_ends_the_shared_connection_so_the_next_call_connects_again(
    short_root, tmp_path, monkeypatch
):
    ssh = tmp_path / "bin" / "ssh"
    ssh.parent.mkdir()
    ssh.write_text(
        '#!/bin/sh\ncase " $* " in *" -O exit "*) echo "$*" > "$0.exit"; exit 0 ;; esac\nexec sleep 5\n'
    )
    ssh.chmod(0o755)
    monkeypatch.setenv("PATH", f"{ssh.parent}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setattr(link_module, "ASK_TIMEOUT_S", 0.3)
    with pytest.raises(Refusal) as refused:
        Link("farm", short_root).ask(("list",))
    assert refused.value.code is ErrorCode.TRANSPORT and "farm" in refused.value.message
    exited = (ssh.parent / "ssh.exit").read_text().strip()
    assert exited.endswith("-O exit -- farm") and f"ControlPath={short_root}/remote/farm.sock" in exited


def test_a_missing_ssh_and_one_that_hangs_are_transport_refusals():
    with pytest.raises(Refusal) as missing:
        run_ssh(["no-such-ssh-binary", "farm"], 1.0)
    assert missing.value.code is ErrorCode.TRANSPORT and "not installed" in missing.value.message
    with pytest.raises(Refusal) as slow:
        run_ssh(["sleep", "5"], 0.2)
    assert slow.value.code is ErrorCode.TRANSPORT and "0.2 s" in slow.value.message
