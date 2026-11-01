"""The JSON contract (`docs/json-output.md`): one envelope per command, built from an Outcome.

    {"v": 1, "ok": bool, "command": str, "device": serial | null,
     "delivery": <Disposition>, "retry": "safe" | "unsafe",     # only for Refused and Acted
     "data": {...} | "error": {"code", "message", "hint", "details"}}

`delivery` and `retry` are computed here from the outcome type and nowhere else, and `retry`
from `delivery` (`Disposition.retry_safe`). No caller can write them.
"""

from __future__ import annotations

import json
from collections.abc import Mapping

from agent_phone.core.commands.find import Found
from agent_phone.core.commands.skills import SkillCatalog, SkillText
from agent_phone.core.device import DeviceList, Listed, Serial
from agent_phone.core.outcome import Acted, Disposition, ErrorCode, Outcome, Read, Refused, Value
from agent_phone.core.phone import (
    Activate,
    InputAction,
    Key,
    Launch,
    LongPress,
    OpenUri,
    Rotate,
    ServerStatus,
    SetClipboard,
    SetPower,
    SetText,
    Stop,
    Swipe,
    Tap,
)
from agent_phone.core.policy.engine import Clear, Commits, Denied, Verdict
from agent_phone.core.snapshot.budget import render_line
from agent_phone.core.snapshot.snapshot import Snapshot

VERSION = 1

HINTS: Mapping[ErrorCode, str] = {
    ErrorCode.STALE_REF: "Take a new snapshot and use a ref from it.",
    ErrorCode.OBSERVE_FIRST: "Input was sent since the last snapshot. Take one and look before acting.",
    ErrorCode.WRONG_DEVICE: "The ref belongs to another device. Drop -d, or pass the device it names.",
    ErrorCode.AMBIGUOUS_TARGET: "Several elements match. Narrow the query, or take a ref from find.",
    ErrorCode.COMMIT_REFUSED: "Grant the listed effect with --commit only when your user asked for it.",
    ErrorCode.DENIED: "A policy rule forbids this on this device. No flag overrides it.",
    ErrorCode.DEVICE_AMBIGUOUS: "Several devices are connected. Pass -d <serial>.",
    ErrorCode.DEVICE_BUSY: "Run the command again when the other process is done. Nothing was sent.",
    ErrorCode.SERVER_UNAVAILABLE: "Run `agent-phone server stop`, then run the command again.",
}
"""Only codes whose recovery is not obvious from the message have a hint."""


def to_wire(command: str, device: Serial | None, outcome: Outcome) -> dict[str, object]:
    wire: dict[str, object] = {"v": VERSION, "ok": True, "command": command, "device": device}
    match outcome:
        case Read():
            wire["data"] = payload_data(outcome.payload)
        case Refused():
            wire["ok"] = False
            wire.update(delivery_keys(Disposition.NOT_DELIVERED))
            wire["error"] = error_object(outcome.code, outcome.message, outcome.details)
        case Acted():
            wire["ok"] = outcome.error is None
            wire.update(delivery_keys(outcome.disposition))
            wire["data"] = acted_data(outcome)
            if outcome.error is not None:
                wire["error"] = error_object(outcome.error, outcome.message, {})
    return wire


def delivery_keys(disposition: Disposition) -> dict[str, object]:
    return {"delivery": disposition.value, "retry": "safe" if disposition.retry_safe else "unsafe"}


def error_object(code: ErrorCode, message: str, details: Mapping[str, object]) -> dict[str, object]:
    """A snapshot in `details`, such as the last read of a `wait` that timed out, prints as the
    snapshot payload does."""
    shown = {key: snapshot_data(v) if isinstance(v, Snapshot) else v for key, v in details.items()}
    return {"code": code.value, "message": message, "hint": HINTS.get(code), "details": shown}


def payload_data(payload: object) -> dict[str, object]:
    match payload:
        case Snapshot():
            return snapshot_data(payload)
        case Found():
            return found_data(payload)
        case DeviceList():
            return {"devices": [device_data(row) for row in payload.devices]}
        case ServerStatus():
            return {
                "running": payload.running,
                "watchdog": payload.watchdog,
                "idle_limit_s": payload.idle_limit_s,
                "idle_for_s": payload.idle_for_s,
            }
        case SkillCatalog():
            return {
                "skills": [
                    {"name": skill.name, "alias": skill.alias, "summary": skill.summary}
                    for skill in payload.skills
                ]
            }
        case SkillText():
            return {"name": payload.skill.name, "content": payload.content}
        case Value():
            if payload.ref is None:
                return {"value": payload.value}
            return {"ref": str(payload.ref), "property": payload.property, "value": payload.value}
        case _:
            raise NotImplementedError(f"no wire form for {type(payload).__name__}")


def snapshot_data(snapshot: Snapshot) -> dict[str, object]:
    return {
        "id": snapshot.id,
        "app": snapshot.package,
        "window": snapshot.window_kind.value,
        "mode": snapshot.mode.value,
        "settled": snapshot.settled.value,
        "keyboard": snapshot.keyboard,
        "dialog": snapshot.dialog,
        "others": [
            {
                "id": other.id,
                "app": other.package,
                "window": other.kind.value,
                "bounds": [other.bounds.left, other.bounds.top, other.bounds.right, other.bounds.bottom],
                "nodes": other.nodes,
            }
            for other in snapshot.others
        ],
        "toasts": list(snapshot.toasts),
        "truncated": snapshot.truncated,
        "tree": [render_line(line, snapshot.id) for line in snapshot.lines],
    }


def found_data(found: Found) -> dict[str, object]:
    """Only a count when nothing was recorded. Otherwise the snapshot that owns the refs of the
    listed matches, and the matches as the lines a snapshot prints."""
    data: dict[str, object] = {"count": found.count}
    if found.snapshot is not None:
        snapshot = found.snapshot
        data |= {
            "id": snapshot.id,
            "app": snapshot.package,
            "window": snapshot.window_kind.value,
            "truncated": snapshot.truncated,
            "matches": [render_line(line, snapshot.id) for line in snapshot.lines],
        }
    return data


def acted_data(acted: Acted) -> dict[str, object]:
    report = acted.report
    target = report.target
    return {
        "input": input_data(report.action),
        "target": None
        if target is None
        else {
            "ref": target.ref,
            "role": target.role.value,
            "name": target.name,
            "at": None if target.point is None else [target.point.x, target.point.y],
        },
        "gate": gate_data(report.verdict),
        "verified_by": report.verified_by,
        "after": None if acted.after is None else snapshot_data(acted.after),
    }


def input_data(action: InputAction) -> dict[str, object]:
    """What was sent. Typed text and clipboard text are never echoed: they can be secrets."""
    match action:
        case Tap(point=p):
            return {"kind": "tap", "at": [p.x, p.y]}
        case LongPress(point=p, duration_ms=ms):
            return {"kind": "long_press", "at": [p.x, p.y], "ms": ms}
        case Activate():
            return {"kind": "activate"}
        case Swipe(start=a, end=b):
            return {"kind": "swipe", "from": [a.x, a.y], "to": [b.x, b.y]}
        case SetText(secret=secret):
            return {"kind": "set_text", "secret": secret}
        case Key(key=key):
            return {"kind": "key", "key": key.value}
        case Launch(package=package):
            return {"kind": "launch", "package": package}
        case Stop(package=package):
            return {"kind": "stop", "package": package}
        case OpenUri(uri=uri, package=package):
            return {"kind": "open_uri", "uri": uri, "package": package}
        case Rotate(orientation=orientation):
            return {"kind": "rotate", "orientation": orientation.value}
        case SetPower(power=power):
            return {"kind": "power", "power": power.value}
        case SetClipboard():
            return {"kind": "set_clipboard"}


def gate_data(verdict: Verdict) -> dict[str, object]:
    """Only a clear or a granted verdict is ever sent, so a denial has no wire form here."""
    match verdict:
        case Clear(reason=reason):
            return {"verdict": "clear", "reason": reason.value}
        case Commits(effects=effects):
            return {"verdict": "commits", "effects": sorted(effect.value for effect in effects)}
        case Denied():
            return {"verdict": "denied", "rule": verdict.rule}


def device_data(row: Listed) -> dict[str, object]:
    data: dict[str, object] = {
        "serial": row.connected.serial,
        "model": row.connected.model,
        "ready": row.connected.ready,
    }
    if row.info is not None:
        info = row.info
        data |= {
            "model": info.model,
            "api": info.api_level,
            "abi": info.abi,
            "display": [info.display.width, info.display.height],
            "density": info.density_dpi,
            "locale": info.locale,
            "ime": info.default_ime,
            "boot_id": info.identity.boot_id,
        }
    if row.problem is not None:
        data["problem"] = row.problem
    data["profile"] = row.profile
    return data


def floor_envelope(
    command: str, device: Serial | None, error: BaseException, unrefunded: bool
) -> dict[str, object]:
    """The CLI's handler for an exception no command caught. INTERNAL, with `delivery_uncertain`
    when the ledger says this process spent a permit it did not refund, else `not_delivered`."""
    disposition = Disposition.DELIVERY_UNCERTAIN if unrefunded else Disposition.NOT_DELIVERED
    message = f"agent-phone failed inside itself with {type(error).__name__}: {error}"
    return {
        "v": VERSION,
        "ok": False,
        "command": command,
        "device": device,
        **delivery_keys(disposition),
        "error": error_object(ErrorCode.INTERNAL, message, {"exception": type(error).__name__}),
    }


def exit_code(outcome: Outcome) -> int:
    """0 ok, 1 an error envelope, 2 argument parse error (the envelope is still printed)."""
    match outcome:
        case Read():
            return 0
        case Refused():
            return 2 if outcome.code is ErrorCode.INVALID_ARGS else 1
        case Acted():
            return 0 if outcome.error is None else 1


def encode(wire: Mapping[str, object]) -> str:
    """UTF-8 JSON with no ASCII escaping and no spaces between tokens, as the contract says."""
    return json.dumps(wire, ensure_ascii=False, separators=(",", ":"))
