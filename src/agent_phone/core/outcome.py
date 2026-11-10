"""What a command produced, and what that says about input reaching the device.

The disposition is never a field a code path fills in. It follows from which outcome type the
command returned:

- `Refused`: nothing left the computer. Disposition `not_delivered`, retry safe.
- `Acted`: a permit was spent and input was handed to the backend. Its `SentState` has no
  "not delivered" member, so an action that sent input cannot be reported as safe to retry.
- `Read`: a read-only command succeeded. No disposition.

The CLI's last-resort handler cannot know which of these an unexpected exception interrupted,
so it asks the ledger (`act/ledger.py`) whether this process spent a permit it did not refund.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent_phone.core.act.intent import ActionReport
    from agent_phone.core.commands.find import Found
    from agent_phone.core.commands.skills import SkillCatalog, SkillText
    from agent_phone.core.device import DeviceList
    from agent_phone.core.phone import ServerStatus
    from agent_phone.core.snapshot.snapshot import RefToken, Snapshot


class ErrorCode(Enum):
    INVALID_ARGS = "INVALID_ARGS"
    POLICY_INVALID = "POLICY_INVALID"
    NO_DEVICE = "NO_DEVICE"
    DEVICE_AMBIGUOUS = "DEVICE_AMBIGUOUS"
    WRONG_DEVICE = "WRONG_DEVICE"
    DEVICE_BUSY = "DEVICE_BUSY"
    SERVER_UNAVAILABLE = "SERVER_UNAVAILABLE"
    NOT_SUPPORTED = "NOT_SUPPORTED"
    SNAPSHOT_NOT_FOUND = "SNAPSHOT_NOT_FOUND"
    STALE_REF = "STALE_REF"
    OBSERVE_FIRST = "OBSERVE_FIRST"
    AMBIGUOUS_TARGET = "AMBIGUOUS_TARGET"
    NOT_FOUND = "NOT_FOUND"
    NO_SURFACE = "NO_SURFACE"
    NOT_ACTIONABLE = "NOT_ACTIONABLE"
    UNSTABLE = "UNSTABLE"
    OCCLUDED = "OCCLUDED"
    INTERRUPTED = "INTERRUPTED"
    COMMIT_REFUSED = "COMMIT_REFUSED"
    DENIED = "DENIED"
    LOCALE_UNSUPPORTED = "LOCALE_UNSUPPORTED"
    TIMEOUT = "TIMEOUT"
    TRANSPORT = "TRANSPORT"
    ACTION_FAILED = "ACTION_FAILED"
    INTERNAL = "INTERNAL"


class Disposition(Enum):
    NOT_DELIVERED = "not_delivered"
    DELIVERY_UNCERTAIN = "delivery_uncertain"
    DELIVERED_UNVERIFIED = "delivered_unverified"
    DELIVERED_VERIFIED = "delivered_verified"

    @property
    def retry_safe(self) -> bool:
        return self is Disposition.NOT_DELIVERED


class SentState(Enum):
    """The dispositions an action can have once input was handed over. NOT_DELIVERED is absent
    on purpose: an adapter that proves nothing left reports `NotSent`, and act() turns that into
    a `Refused` and refunds the permit."""

    UNCERTAIN = "delivery_uncertain"
    UNVERIFIED = "delivered_unverified"
    VERIFIED = "delivered_verified"

    @property
    def disposition(self) -> Disposition:
        return Disposition(self.value)


class Refusal(Exception):
    """Raised anywhere before a permit is minted. Commands convert it to `Refused`.

    Raising it after a permit was minted is a bug that the ledger floor in the CLI handler
    reports as `delivery_uncertain`, never as `not_delivered`.
    """

    def __init__(self, code: ErrorCode, message: str, details: Mapping[str, object] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})


@dataclass(frozen=True, slots=True)
class Refused:
    code: ErrorCode
    message: str
    details: Mapping[str, object] = field(default_factory=dict)

    @staticmethod
    def of(refusal: Refusal) -> Refused:
        return Refused(refusal.code, refusal.message, refusal.details)


@dataclass(frozen=True, slots=True)
class Acted:
    """`error` is set when the input went out but the command still failed: the transport lost
    the answer (TRANSPORT), a `--wait-for` timed out (TIMEOUT), or a read-back contradicted the
    request (ACTION_FAILED). `after` is the observation recorded after the input, when one was.
    `before` is the snapshot the input stood on: the one its ref names, or the device's latest.
    `details` are the error's, such as the interruptions of a refusal that came after an input.
    `inputs` counts the inputs this outcome stands for: one, or the swipes of a scroll that
    repeats, of which `report` and `sent` describe the last and the weakest."""

    sent: SentState
    report: ActionReport
    after: Snapshot | None
    error: ErrorCode | None = None
    message: str = ""
    before: Snapshot | None = None
    details: Mapping[str, object] = field(default_factory=dict)
    inputs: int = 1

    @property
    def disposition(self) -> Disposition:
        return self.sent.disposition


@dataclass(frozen=True, slots=True)
class Value:
    """A scalar answer: `get` text, `is` checks, clipboard text, a screenshot's path. `ref` and
    `property` say what was asked when the answer is about one element. `value` is None when the
    element has no such property, for example the value of a button."""

    value: str | bool | int | tuple[int, ...] | tuple[str, ...] | None
    snapshot: Snapshot | None = None
    ref: RefToken | None = None
    property: str = ""


@dataclass(frozen=True, slots=True)
class Read:
    payload: (
        Snapshot | Found | Value | DeviceList | ServerStatus | SkillCatalog | SkillText | tuple[object, ...]
    )


Outcome = Refused | Acted | Read


def disposition_of(outcome: Outcome) -> Disposition | None:
    match outcome:
        case Refused():
            return Disposition.NOT_DELIVERED
        case Acted():
            return outcome.disposition
        case Read():
            return None
