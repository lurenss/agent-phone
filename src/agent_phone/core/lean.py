"""The lean form of an envelope (`--lean`): what an agent in a loop reads, and nothing it can leave
out. It is made from the full wire object, so it can say nothing the full form does not.

A key is left out when it holds its usual value, and a missing key means that value: `permission_mode`
`ask`, `window` `application`, `mode` `compact`, `keyboard` and `dialog` false, `truncated` 0, no
toast, no interruption, a `clear` gate, nothing verified. Tree lines lose their bounds. What was
sent and at what is left out: the caller named it. So are the system windows of `others` (the bars,
the notification shade, a heads-up notification), which the full form lists.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

BOUNDS = re.compile(r" \[-?\d+,-?\d+,-?\d+,-?\d+\]$")
LINES = ("tree", "added", "gone", "matches")
USUAL = {"window": "application", "mode": "compact", "keyboard": False, "dialog": False, "truncated": 0}


def lean(wire: Mapping[str, object]) -> dict[str, object]:
    out: dict[str, object] = {"ok": wire["ok"]}
    if wire.get("permission_mode") != "ask":
        out["permission_mode"] = wire.get("permission_mode")
    if "delivery" in wire:
        out["delivery"] = wire["delivery"]
    if isinstance(data := wire.get("data"), Mapping):
        out["data"] = lean_data(data)
    if isinstance(error := wire.get("error"), Mapping):
        out["retry"] = wire.get("retry")
        out["error"] = {key: lean_value(value) for key, value in error.items() if value not in (None, {})}
    return out


def lean_data(data: Mapping[str, object]) -> dict[str, object]:
    if isinstance(steps := data.get("steps"), list):
        return {**data, "steps": [lean(step) for step in steps]}
    if "gate" not in data:
        return lean_snapshot(data)
    out: dict[str, object] = {}
    gate = data["gate"]
    if isinstance(gate, Mapping) and gate.get("verdict") != "clear":
        out["gate"] = gate
    if data.get("verified_by") is not None:
        out["verified_by"] = data["verified_by"]
    out["after"] = lean_value(data.get("after"))
    return out


def lean_value(value: object) -> object:
    if isinstance(value, Mapping):
        if any(key in value for key in LINES):
            return lean_snapshot(value)
        return {key: lean_value(inner) for key, inner in value.items()}
    return value


def lean_snapshot(data: Mapping[str, object]) -> dict[str, object]:
    """A snapshot payload, a find payload, or any other read's data, which passes unchanged."""
    out: dict[str, object] = {}
    for key, value in data.items():
        if key in LINES and isinstance(value, list):
            out[key] = [BOUNDS.sub("", line) for line in value]
        elif key == "others" and isinstance(value, list):
            beside = [other for other in value if other.get("window") != "system"]
            if beside:
                out[key] = beside
        elif key in USUAL and value == USUAL[key]:
            continue
        elif key in ("toasts", "interruptions") and not value:
            continue
        else:
            out[key] = value
    return out
