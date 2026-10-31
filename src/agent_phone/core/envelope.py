"""The JSON contract (`docs/json-output.md`): one envelope per command, built from an Outcome.

    {"v": 1, "ok": bool, "command": str, "device": serial | null,
     "delivery": <Disposition>, "retry": "safe" | "unsafe",     # only for Refused and Acted
     "data": {...} | "error": {"code", "message", "hint", "details"}}

`delivery` and `retry` are computed here from the outcome type and nowhere else, and `retry`
from `delivery` (`Disposition.retry_safe`). No caller can write them.
"""

from __future__ import annotations

from collections.abc import Mapping

from agent_phone.core.device import Serial
from agent_phone.core.outcome import Disposition, ErrorCode, Outcome

VERSION = 1

HINTS: Mapping[ErrorCode, str] = {
    ErrorCode.STALE_REF: "Take a new snapshot and use a ref from it.",
    ErrorCode.OBSERVE_FIRST: "Input was sent since the last snapshot. Take one and look before acting.",
    ErrorCode.WRONG_DEVICE: "The ref belongs to another device. Drop -d, or pass the device it names.",
    ErrorCode.AMBIGUOUS_TARGET: "Several elements match. Pick one of the refs in details.candidates.",
    ErrorCode.COMMIT_REFUSED: "Grant the listed effect with --commit only when your user asked for it.",
    ErrorCode.DENIED: "A policy rule forbids this on this device. No flag overrides it.",
    ErrorCode.DEVICE_AMBIGUOUS: "Several devices are connected. Pass -d <serial>.",
}
"""Only codes whose recovery is not obvious from the message have a hint."""


def to_wire(command: str, device: Serial | None, outcome: Outcome) -> dict[str, object]:
    # TODO: Read -> data from payload (Snapshot -> header + rendered lines)
    #   Refused -> ok False, error, delivery not_delivered, retry safe
    #   Acted -> ok (error is None), data = report + after, delivery from sent, retry unsafe
    raise NotImplementedError


def floor_envelope(
    command: str, device: Serial | None, error: BaseException, unrefunded: bool
) -> dict[str, object]:
    """The CLI's handler for an exception no command caught. INTERNAL, with `delivery_uncertain`
    when the ledger says this process spent a permit it did not refund, else `not_delivered`."""
    delivery = Disposition.DELIVERY_UNCERTAIN if unrefunded else Disposition.NOT_DELIVERED
    _ = delivery
    raise NotImplementedError


def exit_code(outcome: Outcome) -> int:
    """0 ok, 1 an error envelope, 2 argument parse error (the envelope is still printed)."""
    raise NotImplementedError
