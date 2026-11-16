"""One ssh host alias, used through a connection that OpenSSH keeps open between commands.

Every call passes `ControlMaster=auto`, so the first one makes the shared connection and the
later ones reuse it (R1-4). OpenSSH closes it after `CONTROL_PERSIST_S` without use. agent-phone
never starts it by hand, and ends it by hand only after an ask that timed out. A connection that
is gone is replaced by the next call (R1-13).

A forward is a port on this computer that reaches a port on the host's loopback. It lives in the
shared connection. A connection that was replaced has none, so `refresh` asks for each again, and
asking for one that is there changes nothing (R1-6). Row ids are those of
`probes/remote/FINDINGS.md`.
"""

from __future__ import annotations

import json
import os
import shlex
import socket
import subprocess
import sys
from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from agent_phone.adapters.remote.wire import WIRE_VERSION
from agent_phone.core.outcome import ErrorCode, Refusal

CONTROL_PERSIST_S = 600
ASK_TIMEOUT_S = 20.0
FORWARD_TRIES = 3
SOCKET_PATH_LIMIT = (104 if sys.platform == "darwin" else 108) - 18
"""ssh binds the socket under the path plus 17 characters first, and the path of a unix socket
holds 104 bytes on macOS and 108 on Linux, with the final zero (R1-14)."""
MISREAD_IN_AN_OPTION = frozenset(" \t%\"'\\$")
"""ssh reads `-o ControlPath=<path>` like a line of its config: a space ends it, a quote must
close, `%h` and `${HOME}` are replaced, and two backslashes become one (R1-19)."""
SSH_OPTIONS = (
    "BatchMode=yes",
    "ControlMaster=auto",
    f"ControlPersist={CONTROL_PERSIST_S}",
    "ServerAliveInterval=15",
    "ServerAliveCountMax=3",
    "ConnectTimeout=10",
)
"""`BatchMode` because no person is there to answer a prompt. The two `ServerAlive` options end a
connection whose network died within 45 s. The alias, its port, user and key come from the user's
own ssh config."""


@dataclass(frozen=True, slots=True)
class Done:
    status: int
    stdout: str
    stderr: str


class TimedOut(Refusal):
    """ssh did not finish in time. When the network of a shared connection died, ssh needs 45 s to
    see it, and every call in that time waits on the dead connection."""


class Run(Protocol):
    def __call__(self, argv: Sequence[str], timeout_s: float) -> Done: ...


def run_ssh(argv: Sequence[str], timeout_s: float) -> Done:
    try:
        done = subprocess.run(
            list(argv),
            capture_output=True,
            text=True,
            errors="replace",
            stdin=subprocess.DEVNULL,
            timeout=timeout_s,
        )
    except FileNotFoundError as error:
        raise Refusal(ErrorCode.TRANSPORT, "ssh is not installed, or it is not on PATH.") from error
    except subprocess.TimeoutExpired as error:
        raise TimedOut(ErrorCode.TRANSPORT, f"ssh did not finish within {timeout_s:g} s.") from error
    return Done(done.returncode, done.stdout, done.stderr)


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class Link:
    def __init__(self, alias: str, state_root: Path, run: Run = run_ssh) -> None:
        self._alias = alias
        self._run = run
        self._socket = state_root / "remote" / f"{alias}.sock"
        self._forwards: dict[int, int] = {}

    def check(self) -> None:
        """ssh and agent-phone must read the path the same way, the system cannot bind a longer
        path, and ssh cannot be told another one. A caller checks before it writes under the state
        root, so a root that can never work is left as it was."""
        if not self._socket.is_absolute():
            raise Refusal(
                ErrorCode.INVALID_ARGS,
                f"The state root {self._socket.parents[1]} is not an absolute path. ssh reads a leading `~` "
                "as the home folder and agent-phone does not, and any other relative path follows the "
                "working directory. Set AGENT_PHONE_HOME to an absolute path.",
            )
        if len(os.fsencode(self._socket)) > SOCKET_PATH_LIMIT:
            raise Refusal(
                ErrorCode.INVALID_ARGS,
                f"The ssh control socket {self._socket} is longer than {SOCKET_PATH_LIMIT} bytes, which "
                "is all the system allows. Set AGENT_PHONE_HOME to a shorter path.",
            )
        if MISREAD_IN_AN_OPTION & set(os.fspath(self._socket)):
            raise Refusal(
                ErrorCode.INVALID_ARGS,
                f"The ssh control socket {self._socket} holds a space, a quote, %, \\ or $, and ssh reads "
                "each of them as something else. Set AGENT_PHONE_HOME to a path without them.",
            )

    def ask(self, words: Sequence[str]) -> Mapping[str, object]:
        """The words go as one argument, joined with `shlex.join`, because ssh joins its arguments
        with spaces and the host splits them again. An ask that times out ends the shared
        connection with `-O exit`, which the local ssh obeys at once, so the next ask does not wait
        on a connection whose network died."""
        self.check()
        self._socket.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            done = self._run(self._ssh("--", self._alias, shlex.join(words)), ASK_TIMEOUT_S)
        except TimedOut as hung:
            with suppress(Refusal):
                self._run(self._ssh("-O", "exit", "--", self._alias), ASK_TIMEOUT_S)
            raise Refusal(
                ErrorCode.TRANSPORT,
                f"The phone host {self._alias} did not answer within {ASK_TIMEOUT_S:g} s. Its shared ssh "
                "connection was ended, so the next command makes a new one.",
            ) from hung
        if done.status == 255:
            reason = (done.stderr.strip().splitlines() or ["ssh gave no reason"])[-1]
            raise Refusal(
                ErrorCode.TRANSPORT,
                f"ssh could not reach the phone host {self._alias}: {reason}. "
                f"Run `ssh {self._alias}` by hand to see why.",
            )
        try:
            answer = json.loads(done.stdout)
        except ValueError:
            answer = None
        if not isinstance(answer, dict) or answer.get("v") != WIRE_VERSION:
            raise Refusal(
                ErrorCode.TRANSPORT,
                f"The phone host {self._alias} did not answer as phone-host version {WIRE_VERSION} does: "
                f"{(done.stdout or done.stderr).strip()[:120]!r}.",
            )
        return answer

    def forward(self, host_port: int) -> int:
        """A free port on this computer that now reaches 127.0.0.1:`host_port` on the host.

        `ssh -L` refuses port 0 (R1-9), so this binds port 0 itself, closes it and asks for that
        number. A number that another process took in between makes ssh fail (R1-7), and the next
        try picks another. `ask` must have run first in this process, so that the connection is
        there.
        """
        for _ in range(FORWARD_TRIES):
            local = free_port()
            if self._forwarding("forward", local, host_port).status == 0:
                self._forwards[local] = host_port
                return local
        raise Refusal(
            ErrorCode.TRANSPORT,
            f"ssh could not forward a port to the phone host {self._alias} in {FORWARD_TRIES} tries.",
        )

    def refresh(self) -> None:
        for local, host_port in self._forwards.items():
            if self._forwarding("forward", local, host_port).status != 0:
                raise Refusal(
                    ErrorCode.TRANSPORT,
                    f"ssh lost the forward to the phone host {self._alias} and could not make it again.",
                )

    def close(self) -> None:
        """Best effort: a forward that stays behind dies with the shared connection."""
        for local, host_port in self._forwards.items():
            with suppress(Refusal):
                self._forwarding("cancel", local, host_port)
        self._forwards.clear()

    def _forwarding(self, action: str, local: int, host_port: int) -> Done:
        """The host side is the literal 127.0.0.1: a forward to `localhost` carries nothing (R1-8)."""
        spec = f"127.0.0.1:{local}:127.0.0.1:{host_port}"
        return self._run(self._ssh("-O", action, "-L", spec, "--", self._alias), ASK_TIMEOUT_S)

    def _ssh(self, *args: str) -> list[str]:
        options = (*SSH_OPTIONS, f"ControlPath={self._socket}")
        return ["ssh", *(part for option in options for part in ("-o", option)), *args]
