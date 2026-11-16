"""The words agent-phone sends to `phone-host` and the JSON it answers, in one place.

`host/phone_host.py` writes this JSON and this module reads its fields. `Link.ask` checks only that
an answer is one object of this `WIRE_VERSION`. `tests/test_remote_wire.py` runs the real script
against a fake adb server and feeds its output to these functions, so a field renamed on one side
fails the suite.

Nothing outside this module sees the JSON. Callers get `Connected`, `Lease` and `Grant`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from agent_phone.core.device import Connected, Lease, Serial
from agent_phone.core.outcome import ErrorCode, Refusal

WIRE_VERSION = 1


@dataclass(frozen=True, slots=True)
class Listing:
    phones: tuple[Connected, ...]
    adb_version: int


@dataclass(frozen=True, slots=True)
class Grant:
    tenure: str
    host_port: int
    lease: Lease


@dataclass(frozen=True, slots=True)
class Busy:
    lease: Lease


def list_words(holder: str) -> tuple[str, ...]:
    return ("list", "--holder", holder)


def lease_words(serial: Serial, holder: str, task: str, ttl_s: int, device_port: int) -> tuple[str, ...]:
    """The task is joined to its flag, so a task that starts with a dash is still a task."""
    return (
        "lease",
        serial,
        "--holder",
        holder,
        f"--task={task}",
        "--ttl",
        str(ttl_s),
        "--port",
        str(device_port),
    )


def release_words(serial: Serial, holder: str) -> tuple[str, ...]:
    return ("release", serial, "--holder", holder)


def parse_listing(answer: Mapping[str, object]) -> Listing:
    if answer.get("ok") is False:
        raise Refusal(ErrorCode.TRANSPORT, f"The phone host could not list its phones: {said(answer)}")
    phones = tuple(
        Connected(
            Serial(field(row, "serial", str)),
            field(row, "model", str),
            field(row, "state", str) == "device",
            None if row.get("lease") is None else lease_of(row),
        )
        for row in rows(answer)
    )
    return Listing(phones, field(answer, "adb", int))


def parse_grant(answer: Mapping[str, object], serial: Serial) -> Grant | Busy:
    if answer.get("ok") is True:
        return Grant(field(answer, "id", str), field(answer, "port", int), lease_of(answer))
    match answer.get("error"):
        case "busy":
            return Busy(lease_of(answer))
        case "no_device":
            raise Refusal(
                ErrorCode.NO_DEVICE,
                f"The phone host's adb does not list {serial} as ready. It may be unplugged or unauthorized.",
                {"serial": serial},
            )
        case _:
            raise Refusal(ErrorCode.TRANSPORT, f"The phone host did not lease {serial}: {said(answer)}")


def said(answer: Mapping[str, object]) -> str:
    return str(answer.get("message") or answer.get("error") or "it gave no reason.")


def rows(answer: Mapping[str, object]) -> list[Mapping[str, object]]:
    phones = field(answer, "phones", list)
    if not all(isinstance(row, Mapping) for row in phones):
        raise Refusal(ErrorCode.TRANSPORT, "The phone host's list holds a row that is not an object.")
    return phones


def lease_of(holder: Mapping[str, object]) -> Lease:
    lease = field(holder, "lease", dict)
    return Lease(
        field(lease, "by", str),
        field(lease, "task", str),
        field(lease, "held_s", int),
        field(lease, "free_in_s", int),
        field(lease, "mine", bool),
    )


def field[T](answer: Mapping[str, object], name: str, kind: type[T]) -> T:
    """`True` is an int in Python, and not one here."""
    value = answer.get(name)
    if not isinstance(value, kind) or isinstance(value, bool) != (kind is bool):
        raise Refusal(
            ErrorCode.TRANSPORT,
            f"The phone host's answer has no {kind.__name__} `{name}`. Its script and this agent-phone "
            "may be of different versions.",
            {"field": name},
        )
    return value
