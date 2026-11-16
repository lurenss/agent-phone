"""A `PhoneHub` for the phones of a phone host: any adb backend, with the host's lease around it.

`remote_hub` is the whole public interface of this package. It wraps the hub that the caller
builds for a local adb, and changes three things about it:

- `connected()` asks the host, so every row also says who holds the phone;
- `open()` takes the lease before the backend touches the phone, and the phone it returns keeps
  the lease before every read and input;
- the backend's adb talks to the host's adb server through a forward, and its request for a port
  to the on-device server is answered with the port the lease already carries.

Nothing in the wrapped backend changes, and the device lock of this computer still serializes its
own processes before any of this runs.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Callable, Iterator, Sequence
from contextlib import AbstractContextManager, contextmanager
from functools import cached_property
from pathlib import Path

from agent_phone.adapters.remote.claim import Claim, holder_id
from agent_phone.adapters.remote.link import Link, Run, run_ssh
from agent_phone.adapters.remote.wire import Listing, list_words, parse_listing
from agent_phone.adapters.uiautomator2.adb import DEFAULT_TIMEOUT_S, Adb, AdbResult
from agent_phone.core.device import Connected, DeviceInfo, DeviceState, Serial
from agent_phone.core.outcome import ErrorCode, Refusal
from agent_phone.core.phone import BackendServer, Delivery, NotSent, Permit, Phone, PhoneHub, ServerStatus
from agent_phone.core.screen import Screen
from agent_phone.core.wait.clock import Clock

HOST_ADB_PORT = 5037
ADB_VERSION = re.compile(r"version \d+\.\d+\.(\d+)")


@contextmanager
def remote_hub(
    alias: str,
    state_root: Path,
    adb: Adb,
    make_hub: Callable[[Adb], PhoneHub],
    *,
    device_port: int,
    task: str,
    linger: bool,
    wait_s: float,
    clock: Clock,
    run: Run = run_ssh,
) -> Iterator[PhoneHub]:
    """The phones plugged into the ssh host `alias`.

    `make_hub` builds the backend's hub over the adb it is given, and `device_port` is the port
    that backend's server listens on, on the phone. `task` is what other people see next to this
    holder's name. With `linger`, a closed phone keeps its lease until it runs out, which is what a
    command line that runs one process per step wants. Leaving the block cancels this process's
    forwards. It makes no connection and no file until the first call.
    """
    hub = RemoteHub(alias, state_root, adb, make_hub, device_port, task, linger, wait_s, clock, run)
    try:
        yield hub
    finally:
        hub.close()


class RemoteHub:
    def __init__(
        self,
        alias: str,
        state_root: Path,
        adb: Adb,
        make_hub: Callable[[Adb], PhoneHub],
        device_port: int,
        task: str,
        linger: bool,
        wait_s: float,
        clock: Clock,
        run: Run,
    ) -> None:
        self._link = Link(alias, state_root, run)
        self._state_root = state_root
        self._device_port = device_port
        self._task = task
        self._linger = linger
        self._wait_s = wait_s
        self._clock = clock
        self._claims: dict[Serial, Claim] = {}
        self._listing: Listing | None = None
        remote_adb = RemoteAdb(adb, self._link.forward, self._claim_of, self._adb_version, device_port)
        self._inner = make_hub(remote_adb)

    @cached_property
    def _holder(self) -> str:
        self._link.check()
        return holder_id(self._state_root)

    def connected(self) -> tuple[Connected, ...]:
        self._listing = parse_listing(self._link.ask(list_words(self._holder)))
        return self._listing.phones

    def inspect(self, serial: Serial) -> DeviceInfo:
        """It takes no lease, as locally it takes no lock: it reads facts and starts nothing."""
        return self._inner.inspect(serial)

    def server(self, serial: Serial) -> BackendServer:
        return LeasedServer(self._inner.server(serial), lambda: self._claimed(serial))

    def open(self, serial: Serial, first_read: bool = False) -> Phone:
        claim = self._take(serial)
        try:
            return LeasedPhone(self._inner.open(serial, first_read), claim, lambda: self._drop(serial))
        except BaseException:
            self._drop(serial)
            raise

    def close(self) -> None:
        self._link.close()

    def _take(self, serial: Serial) -> Claim:
        claim = self._claims[serial] = Claim(
            self._link,
            serial,
            self._holder,
            self._task,
            self._device_port,
            self._linger,
            self._clock,
            self._wait_s,
        )
        try:
            claim.take()
        except BaseException:
            self._drop(serial)
            raise
        return claim

    def _drop(self, serial: Serial) -> None:
        claim = self._claims.pop(serial, None)
        if claim is not None:
            claim.drop()

    @contextmanager
    def _claimed(self, serial: Serial) -> Iterator[None]:
        self._take(serial)
        try:
            yield
        finally:
            self._drop(serial)

    def _claim_of(self, serial: Serial) -> Claim:
        if serial not in self._claims:
            raise Refusal(
                ErrorCode.INTERNAL, f"The backend asked for a port to {serial} with no lease on it."
            )
        return self._claims[serial]

    def _adb_version(self) -> int:
        if self._listing is None:
            self.connected()
        assert self._listing is not None
        return self._listing.adb_version


class LeasedPhone:
    """`inject` never raises for a lost lease. It returns `NotSent` with the refusal's code, so the
    ledger refunds the permit and the outcome is `not_delivered`, which is true: nothing left this
    computer."""

    def __init__(self, inner: Phone, claim: Claim, forget: Callable[[], None]) -> None:
        self._inner = inner
        self._claim = claim
        self._forget = forget

    def info(self) -> DeviceInfo:
        return self._inner.info()

    def read(self) -> Screen:
        self._claim.keep()
        return self._inner.read()

    def state(self) -> DeviceState:
        self._claim.keep()
        return self._inner.state()

    def inject(self, permit: Permit) -> Delivery:
        try:
            self._claim.keep()
        except Refusal as refusal:
            return NotSent(refusal.code, refusal.message)
        return self._inner.inject(permit)

    def clipboard(self) -> str | None:
        self._claim.keep()
        return self._inner.clipboard()

    def screenshot(self) -> bytes:
        self._claim.keep()
        return self._inner.screenshot()

    def close(self) -> None:
        try:
            self._inner.close()
        finally:
            self._forget()


class LeasedServer:
    """`BackendServer`. `start` and `stop` change what another holder's commands depend on, so
    they run inside a claim. `status` only looks."""

    def __init__(self, inner: BackendServer, claimed: Callable[[], AbstractContextManager[None]]) -> None:
        self._inner = inner
        self._claimed = claimed

    def status(self) -> ServerStatus:
        return self._inner.status()

    def start(self) -> ServerStatus:
        with self._claimed():
            return self._inner.start()

    def stop(self) -> ServerStatus:
        with self._claimed():
            return self._inner.stop()


class RemoteAdb:
    """`Adb` for a server that runs on the phone host.

    Every command runs the local adb client as `adb -H 127.0.0.1 -P <forwarded port> ...`. The
    address is written as digits on purpose: adb starts a server of its own when it cannot reach
    `localhost`, and never for this form (R2-1, R2-3 in `probes/remote/FINDINGS.md`).

    A `forward` is the one adb command whose effect lands on the server's computer, where this
    computer cannot reach it. None is sent. The answer to `forward tcp:0 tcp:<device port>` is the
    claim's port, which already reaches that device port. Removing a forward and listing them
    answer with nothing, because the host's ports belong to its leases.

    Only `shell`, `push` and `devices` go to the host, which is all the backend sends. The host's
    server is shared, and a `kill-server`, `reconnect` or `reboot` through the tunnel would cut
    every other holder off.

    Before its first command it compares the local client's protocol number with the host's. An
    adb client kills a server whose number differs from its own (R2-4), and the host's server is
    shared, so a difference is `Refusal(TRANSPORT)` that names both numbers.
    """

    def __init__(
        self,
        local: Adb,
        forward: Callable[[int], int],
        claim_of: Callable[[Serial], Claim],
        host_version: Callable[[], int],
        device_port: int,
    ) -> None:
        self._local = local
        self._forward = forward
        self._claim_of = claim_of
        self._host_version = host_version
        self._device_port = device_port
        self._port: int | None = None
        self._starting = threading.Lock()

    def run(self, args: Sequence[str], timeout_s: float = DEFAULT_TIMEOUT_S) -> AdbResult:
        match tuple(args):
            case ("-s", serial, "forward", "tcp:0", device) if device == f"tcp:{self._device_port}":
                return AdbResult(0, f"{self._claim_of(Serial(serial)).local_port}\n", "")
            case ("-s", _, "forward", "--remove", _) | ("forward", "--list"):
                return AdbResult(0, "", "")
            case ("-s", _, "forward", *_) | ("forward", *_):
                raise Refusal(
                    ErrorCode.INTERNAL,
                    f"`adb {' '.join(args)}` would open a port on the phone host, where this computer "
                    "cannot reach it.",
                )
            case ("-s", _, "shell" | "push", *_) | ("devices", *_):
                return self._local.run(("-H", "127.0.0.1", "-P", str(self._server_port()), *args), timeout_s)
        raise Refusal(
            ErrorCode.INTERNAL,
            f"`adb {' '.join(args)}` is not a command agent-phone sends to a phone host. Its adb server is "
            "shared, so only `shell`, `push` and `devices` go there.",
        )

    def _server_port(self) -> int:
        """The backend reads the facts on a second thread while it starts its server
        (`first_read.overlap`), so the first use is locked."""
        with self._starting:
            if self._port is None:
                host = self._host_version()
                found = ADB_VERSION.search(self._local.run(("version",)).stdout)
                if found is None or int(found[1]) != host:
                    mine = "an unknown protocol" if found is None else f"protocol {found[1]}"
                    raise Refusal(
                        ErrorCode.TRANSPORT,
                        f"This computer's adb speaks {mine} and the phone host's adb server speaks "
                        f"protocol {host}. An adb client kills a server of another protocol, so nothing "
                        "was sent. Install the adb version that the phone host runs.",
                        {"host_adb": host},
                    )
                self._port = self._forward(HOST_ADB_PORT)
            return self._port
