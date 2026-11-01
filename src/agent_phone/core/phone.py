"""The backend contract. uiautomator2 today, an app_process server or an AccessibilityService later.

A backend reads and it injects. It never decides what to read for, what a tap means, or whether
it is allowed: core hands it a `Permit`, which only `act/ledger.py` can construct, and
`tests/test_architecture.py` pins both facts by AST:

- `Permit(` is called only in `core/act/ledger.py`;
- `.inject(` is called only in `core/act/act.py`.

So every input that reaches any backend went through resolution, the policy engine and a
persisted ledger spend, in that order, and through one call site.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Protocol

from agent_phone.core.device import Connected, DeviceIdentity, DeviceInfo, DeviceState, Package, Power, Serial
from agent_phone.core.geometry import Point, Rect
from agent_phone.core.outcome import ErrorCode, Refusal
from agent_phone.core.screen import Screen

if TYPE_CHECKING:
    from agent_phone.core.policy.engine import Grant, Verdict


@dataclass(frozen=True, slots=True)
class NodeAddress:
    """Enough for a backend to find one node again on its own side, without coordinates.

    uiautomator2's `setText` takes a UiSelector, not a node, so its adapter builds a selector
    from these fields and must prove on the device that it matches exactly one node with these
    bounds before it writes (`adapters/uiautomator2/address.py`).
    """

    package: Package
    class_name: str
    resource_id: str
    text: str
    content_desc: str
    bounds: Rect
    path: tuple[int, ...]
    native_id: str | None


class KeyName(Enum):
    BACK = "back"
    HOME = "home"
    RECENTS = "recents"
    ENTER = "enter"


class Orientation(Enum):
    PORTRAIT = "portrait"
    LANDSCAPE = "landscape"
    AUTO = "auto"


@dataclass(frozen=True, slots=True)
class Tap:
    """A touch at `point`. `expect` is the node core proved will receive it; an adapter may log
    it but never re-targets with it."""

    point: Point
    expect: NodeAddress


@dataclass(frozen=True, slots=True)
class LongPress:
    point: Point
    expect: NodeAddress
    duration_ms: int


@dataclass(frozen=True, slots=True)
class Activate:
    """ACTION_CLICK on the node itself, for backends with Capability.SEMANTIC_CLICK."""

    node: NodeAddress


@dataclass(frozen=True, slots=True)
class Swipe:
    start: Point
    end: Point
    duration_ms: int


@dataclass(frozen=True, slots=True)
class SetText:
    field: NodeAddress
    text: str
    secret: bool


@dataclass(frozen=True, slots=True)
class Key:
    key: KeyName


@dataclass(frozen=True, slots=True)
class Launch:
    package: Package


@dataclass(frozen=True, slots=True)
class Stop:
    package: Package


@dataclass(frozen=True, slots=True)
class OpenUri:
    """A link, opened with the VIEW action, or an intent URI that names only an action and
    optionally a package (`intent_of`). Nothing else an intent URI can carry, such as a
    component, extras or flags, is accepted."""

    uri: str
    package: Package | None


INTENT_PREFIX = "intent:#Intent;"
INTENT_KEYS = frozenset({"action", "package"})
NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+")


def intent_of(open: OpenUri) -> tuple[str, Package | None] | None:
    """The action and package of an intent URI, or None for a link. Raises `Refusal(INVALID_ARGS)`
    for a URI with no scheme, and for an intent URI with data or any key but action and package."""
    scheme, colon, _ = open.uri.partition(":")
    if not colon or not scheme or not scheme[0].isalpha():
        raise Refusal(ErrorCode.INVALID_ARGS, f"{open.uri!r} has no scheme, such as https: or intent:.")
    if scheme.casefold() != "intent":
        return None
    body = open.uri[len(INTENT_PREFIX) :].removesuffix(";end") if open.uri.endswith(";end") else None
    pairs = (
        [entry.partition("=") for entry in (body or "").split(";")]
        if open.uri.startswith(INTENT_PREFIX)
        else []
    )
    values = {key: value for key, eq, value in pairs if eq and key in INTENT_KEYS and NAME.fullmatch(value)}
    if not pairs or len(values) != len(pairs) or "action" not in values:
        raise Refusal(
            ErrorCode.INVALID_ARGS,
            f"{open.uri!r} is not an intent agent-phone opens. Write intent:#Intent;action=<action>;end, "
            "with package=<package>; before end if needed, and nothing else.",
        )
    package = Package(values["package"]) if "package" in values else open.package
    if open.package is not None and package != open.package:
        raise Refusal(
            ErrorCode.INVALID_ARGS, f"The intent names {package}, and --package names {open.package}."
        )
    return values["action"], package


@dataclass(frozen=True, slots=True)
class Rotate:
    orientation: Orientation


@dataclass(frozen=True, slots=True)
class SetPower:
    power: Power


@dataclass(frozen=True, slots=True)
class SetClipboard:
    text: str


InputAction = (
    Tap
    | LongPress
    | Activate
    | Swipe
    | SetText
    | Key
    | Launch
    | Stop
    | OpenUri
    | Rotate
    | SetPower
    | SetClipboard
)


@dataclass(frozen=True, slots=True)
class Permit:
    """One input, judged and paid for. The verdict travels with it so traces and test fakes
    record what the engine decided about each input that was really sent."""

    device: DeviceIdentity
    epoch: int
    action: InputAction
    verdict: Verdict
    grant: Grant


class Ack(Enum):
    """ACKNOWLEDGED: the backend answered that it performed the input. UNACKNOWLEDGED: the
    request may have reached the device and no answer came back (timeout, reset after write)."""

    ACKNOWLEDGED = "acknowledged"
    UNACKNOWLEDGED = "unacknowledged"


@dataclass(frozen=True, slots=True)
class NotSent:
    """The backend can prove no input left: refused before the request was written, or the
    device answered that it did nothing (no node matched the selector)."""

    code: ErrorCode
    detail: str


@dataclass(frozen=True, slots=True)
class Sent:
    ack: Ack
    detail: str


Delivery = NotSent | Sent


@dataclass(frozen=True, slots=True)
class ServerStatus:
    """The backend's on-device server, as the phone reports it. `idle_limit_s` is the limit the
    running watchdog was started with, and `idle_for_s` the time since the last client use. Both
    are None when no server runs."""

    running: bool
    watchdog: bool
    idle_limit_s: int | None
    idle_for_s: int | None


class BackendServer(Protocol):
    """The lifetime of a backend's on-device server. `start` and `stop` are idempotent, and each
    returns the status that follows it."""

    def status(self) -> ServerStatus: ...

    def start(self) -> ServerStatus: ...

    def stop(self) -> ServerStatus: ...


class Phone(Protocol):
    """One connected device. Every method either returns core types or raises `Refusal`.

    `inject` sends its action exactly once. It never retries, because only it knows how far
    the request got, and a retry after the request was written can double a commit.
    `close` releases what `PhoneHub.open` acquired and leaves the device's server running.
    """

    def info(self) -> DeviceInfo: ...

    def read(self) -> Screen: ...

    def state(self) -> DeviceState: ...

    def inject(self, permit: Permit) -> Delivery: ...

    def clipboard(self) -> str | None: ...

    def screenshot(self) -> bytes: ...

    def close(self) -> None: ...


class PhoneHub(Protocol):
    """The transport that lists devices and opens one. adb for every backend planned so far.

    `inspect` reads a device's facts and starts nothing. `server` is the handle for the
    backend's on-device server, which `open` starts on demand. `first_read` says that the caller
    reads once, straight after opening, so the backend may take that read while it learns the
    device's facts. A caller that does anything else first must leave it False.
    """

    def connected(self) -> tuple[Connected, ...]: ...

    def inspect(self, serial: Serial) -> DeviceInfo: ...

    def server(self, serial: Serial) -> BackendServer: ...

    def open(self, serial: Serial, first_read: bool = False) -> Phone: ...
