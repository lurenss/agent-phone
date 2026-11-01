#!/usr/bin/env python3
"""Write a device's compatibility card from a run's files. Run it from the repo root:

    uv run python -I .claude/skills/port-android-device/scripts/card.py <run> <name>

It reads `<run>/facts.json` and `<run>/survey.jsonl`, and `<run>/fixtures.json` and `<run>/apps.jsonl`
when they exist, and writes `docs/devices/<name>.md`: the device facts, done-when 4, the input journey,
the screen reads and anomalies, the apps, the hints, and an empty `## Fixes and notes` that the person
bringing the phone up fills. Run again, it keeps whatever stands under that heading. It then adds or
updates the device's row in `docs/devices/README.md`, which it creates with the columns name, model,
Android, language, status and card. The status is `works`, `works with limits` or `blocked`, by the
rules in `card_status.py`. It reads no phone.

The card is committed, so it holds no text from a screen: a sample label of an app appears only when
`probes/android/ui_labels.txt` lists it, and the others are counted.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))

from card_status import Evidence, Status, done_when_4, status_of  # noqa: E402
from device_calls import REPO, device_name, run_folder  # noqa: E402

DOCS = REPO / "docs" / "devices"
LABELS = REPO / "probes" / "android" / "ui_labels.txt"
NOTES = "## Fixes and notes"
INDEX_HEAD = ("name", "model", "Android", "language", "status", "card")
ACTION = re.compile(r"action=([^;]+)")
INDEX_INTRO = """# Device cards

One card for each device brought up with the port-android-device skill: its facts, whether it passes
done-when 4, the input journey, the screen reads, the apps swept and what had to be fixed. A card is
written by `.claude/skills/port-android-device/scripts/card.py`, which keeps the text under its
`## Fixes and notes`.

The status of a device:

- `works`: agent-phone reads and drives it, and every check passed.
- `works with limits`: it does, with a limit the card names, such as a second display, a language the
  policy does not cover, or a check that failed.
- `blocked`: agent-phone cannot read or drive it. The card names why.

"""


def say(value: object) -> object:
    return "unknown" if value is None else value


def cell(value: object) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value).replace("|", "/").replace("\n", " ")


def table(head: tuple[str, ...], rows: list[tuple[object, ...]]) -> list[str]:
    lines = ["| " + " | ".join(head) + " |", "| " + " | ".join("---" for _ in head) + " |"]
    return lines + ["| " + " | ".join(cell(c) for c in row) + " |" for row in rows] + [""]


def facts_section(facts: dict) -> list[str]:
    displays = "; ".join(
        f"{d['id']}: {d['width']}x{d['height']} {d.get('state') or '?'}" for d in facts["displays"]
    )
    covered = {True: "covered", False: "not covered", None: "unknown"}[facts.get("language_covered")]
    rows = [
        ("Serial", facts["serial"]),
        ("Manufacturer, brand", f"{say(facts['manufacturer'])}, {say(facts['brand'])}"),
        ("Model, device", f"{say(facts['model'])}, {say(facts['device'])}"),
        ("Android", f"{say(facts['release'])} (API {say(facts['api'])})"),
        ("ABI", facts["abi"]),
        ("Locale", f"{say(facts['locale'])}, language {say(facts['language'])}, {covered} by the policy"),
        ("Policy languages", ", ".join(facts["policy_languages"])),
        ("Emulator", facts["emulator"]),
        ("Displays", displays or None),
        ("Keys go to display", facts["top_focused_display"]),
        ("Screen awake", facts["awake"]),
        ("Bluetooth on", facts["bluetooth_on"]),
        ("Keyboard", facts["ime"]),
    ]
    return ["## Device facts", "", *table(("Fact", "Value"), rows)]


def done_when_section(ev: Evidence) -> list[str]:
    rows = []
    for screen in ("launcher", "settings", "dialog"):
        warm, settle, read = (
            ev.of_screen(n, screen) for n in ("warm_snapshot", "warm_settle", "screen_read")
        )
        if warm is None:
            rows.append((screen, "not measured", *["-"] * 9))
            continue
        low, high = warm["range_ms"]
        small, large = warm["bytes"]
        settled = f"{settle['settled']} of {settle['runs']}" if settle else None
        rows.append(
            (
                screen,
                (read or {}).get("app"),
                warm["runs"],
                warm["errors"],
                warm["wrong_screen"],
                warm["median_ms"],
            )
            + (
                f"{low} to {high}",
                f"{small} to {large}",
                warm["under_8_kb"],
                settled,
                (settle or {}).get("median_ms"),
            )
        )
    head = ("Screen", "App", "Runs", "Errors", "Wrong screen", "Median ms", "Range ms", "Bytes", "Under 8 KB")
    failures = done_when_4(ev)
    verdict = (
        ["Done-when 4 is met on Settings and the dialog."]
        if not failures
        else [
            "Done-when 4 is not met:",
            "",
            *[f"- {failure}" for failure in failures],
        ]
    )
    return [
        "## Done-when 4",
        "",
        "Settings and the system dialog must have no error and no wrong screen, a median under 400 ms,"
        " output under 8 KB and every settled read settled. The launcher is measured for reference.",
        "",
        *table((*head, "Settled", "Settle median ms"), rows),
        *verdict,
        "",
    ]


def describe(argv: list[str]) -> str:
    if argv[0] == "open-url" and (action := ACTION.search(argv[1])):
        return f"open-url {action[1]}"
    return " ".join(argv)


def journey_section(ev: Evidence) -> list[str]:
    rows = [
        (
            s["step"],
            describe(s["argv"]),
            s["delivery"],
            s["verified_by"],
            s["error"],
            s["after_app"],
            s["changed"],
        )
        for s in ev.checks("input")
    ]
    sent = next(iter(ev.checks("inputs")), {}).get("sent", [])
    head = ("Step", "Input", "Delivery", "Verified by", "Error", "App after", "Screen changed")
    return [
        "## Input journey",
        "",
        "Every input read the screen first. The scrolls prove swipes, and the back from About proves keys.",
        "",
        *table(head, rows),
        f"{len(sent)} inputs were sent. None was a tap.",
        "",
    ]


def screens_section(ev: Evidence) -> list[str]:
    reads = [
        (
            r["screen"],
            r["app"],
            r["window"],
            r["dialog"],
            r["settled"],
            r["focus_app"],
            r["agrees"],
            r["reads"],
        )
        for r in ev.checks("screen_read")
    ]
    head = ("Screen", "App", "Window", "Dialog", "Settled", "Focus app", "Agrees", "Reads")
    out = ["## Screen reads and anomalies", "", *table(head, reads)]
    for screen in ("launcher", "settings", "dialog"):
        for line in ev.checks(f"{screen}_not_shown"):
            out += [
                f"- The {screen} was not shown in {line['reads']} reads. The last read named {line['app']}.",
                "",
            ]
    dumps = [d["screen"] for d in ev.checks("raw_dump") if d["ok"]]
    out += [f"Raw dumps saved: {', '.join(dumps) or 'none'}.", ""]
    if ev.fixtures is None:
        return [*out, "No fixtures were made. `fixtures.py` has not run.", ""]
    screens = ev.fixtures["screens"]
    fixture_rows = [
        (name, s["active"], s["dialog"], len(s["windows"]), s["other_display_roots"], s["rotation"])
        + ("x".join(map(str, s["display"])) if s["display"] else None, ", ".join(s["others"]) or None)
        for name, s in screens.items()
    ]
    head = (
        "Screen",
        "Active",
        "Dialog",
        "Windows",
        "Roots of another display",
        "Rotation",
        "Display",
        "Others",
    )
    out += ["Fixtures, as `parse_hierarchy` and `select_surface` read them:", "", *table(head, fixture_rows)]
    found = ev.fixtures["anomalies"]
    out += [f"- {a['screen']}: {a['rule']}: {a['detail']}" for a in found] if found else ["No anomaly."]
    out += [
        f"- No fixture of the {screen}: no raw dump was saved." for screen in ev.fixtures.get("missing", [])
    ]
    return [*out, ""]


def shown_samples(samples: dict[str, list[str]], labels: set[str]) -> list[str]:
    """One line for each effect: the sample labels that `ui_labels.txt` lists, and a count of the rest."""
    lines = []
    for effect, names in samples.items():
        known = [f"`{n}`" for n in names if n in labels]
        hidden = len(names) - len(known)
        extra = f"{hidden} not shown" if hidden else ""
        lines.append(f"{effect}: " + "; ".join(part for part in (", ".join(known), extra) if part))
    return lines


def apps_section(ev: Evidence, labels: set[str]) -> list[str]:
    if not ev.apps:
        return ["## Apps", "", "No sweep was run.", ""]
    rows, samples = [], []
    for app in ev.apps:
        by_effect = ", ".join(f"{effect} {n}" for effect, n in app.get("commits", {}).items()) or None
        wait = f"wait {app['wait_error']}" if app.get("wait_error") else None
        note = app.get("skipped") or app.get("aborted") or app.get("error") or app.get("launch_error") or wait
        rows.append(
            (
                app["package"],
                app["launched"],
                app.get("settled_ms"),
                app.get("snapshot_lines"),
                app.get("targets"),
            )
            + (app.get("clear"), by_effect, app.get("denied"), app.get("refused"), note)
        )
        samples += [f"- {app['package']}: {line}" for line in shown_samples(app.get("samples", {}), labels)]
    head = (
        "Package",
        "Launched",
        "Settled ms",
        "Snapshot lines",
        "Targets",
        "Clear",
        "Commits",
        "Denied",
        "Refused",
    )
    sampled = ["Sample labels:", "", *samples, ""] if samples else []
    return ["## Apps", "", *table((*head, "Note"), rows), *sampled]


def hints_section(facts: dict) -> list[str]:
    return ["## Hints", "", *([f"- {hint}" for hint in facts["hints"]] or ["None."]), ""]


def preserved_notes(existing: str | None) -> str:
    """Everything after the `## Fixes and notes` line of the card on disk, which the runner wrote."""
    if existing is None:
        return ""
    lines = existing.splitlines(keepends=True)
    at = next((i for i, line in enumerate(lines) if line.rstrip() == NOTES), None)
    return "".join(lines[at + 1 :]) if at is not None else ""


def render(name: str, ev: Evidence, run: Path, notes: str, labels: set[str]) -> str:
    status, reasons = status_of(ev)
    facts = ev.facts
    head = [
        f"# {say(facts['manufacturer'])} {say(facts['model'])} ({name})",
        "",
        f"**Status: {status.value}.**",
        "",
        *([f"- {reason}" for reason in reasons] or ["No limit was found."]),
        "",
        f"Source run: `{run.name}`, kept under `~/.agent-phone/verify/`, outside git.",
        "",
    ]
    body = [
        *facts_section(facts),
        *done_when_section(ev),
        *journey_section(ev),
        *screens_section(ev),
        *apps_section(ev, labels),
        *hints_section(facts),
    ]
    return "\n".join([*head, *body, NOTES]) + "\n" + notes


def index_row(name: str, facts: dict, status: Status) -> str:
    language = f"{say(facts['locale'])}" + (
        " (not covered)" if facts.get("language_covered") is False else ""
    )
    model = f"{say(facts['manufacturer'])} {say(facts['model'])}"
    cells = (name, model, f"{say(facts['release'])} (API {say(facts['api'])})")
    return (
        "| " + " | ".join(cell(c) for c in (*cells, language, status.value, f"[{name}.md]({name}.md)")) + " |"
    )


def update_index(text: str | None, name: str, row: str) -> str:
    """Replace the row of `name`, or add it under the table. The text around the table stays."""
    lines = (text if text is not None else INDEX_INTRO).splitlines()
    rows = [i for i, line in enumerate(lines) if line.startswith("| ") and not line.startswith("| ---")]
    heads = [i for i in rows if lines[i].split("|")[1].strip() == INDEX_HEAD[0]]
    if not heads:
        header = "| " + " | ".join(INDEX_HEAD) + " |"
        lines += ["", header, "| " + " | ".join("---" for _ in INDEX_HEAD) + " |", row]
        return "\n".join(lines).lstrip("\n") + "\n"
    body = [i for i in rows if i > heads[0]]
    own = next((i for i in body if lines[i].split("|")[1].strip() == name), None)
    if own is not None:
        lines[own] = row
    else:
        lines.insert((body[-1] if body else heads[0] + 1) + 1, row)
    return "\n".join(lines) + "\n"


def load(run: Path) -> Evidence:
    def lines(name: str) -> tuple[dict, ...]:
        path = run / name
        return tuple(
            json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
        )

    try:
        facts = json.loads((run / "facts.json").read_text(encoding="utf-8"))
        survey = lines("survey.jsonl")
    except (OSError, ValueError):
        sys.exit(f"card: {run} needs facts.json and survey.jsonl. Run facts.py and survey.py first.")
    fixtures = run / "fixtures.json"
    return Evidence(
        facts,
        survey,
        json.loads(fixtures.read_text(encoding="utf-8")) if fixtures.is_file() else None,
        lines("apps.jsonl") if (run / "apps.jsonl").is_file() else (),
    )


def main(argv: list[str], docs: Path = DOCS) -> int:
    parser = argparse.ArgumentParser(prog="card.py", description="Write a device's compatibility card.")
    parser.add_argument("run", type=run_folder)
    parser.add_argument("name", type=device_name)
    args = parser.parse_args(argv)
    ev = load(args.run)
    labels = set(LABELS.read_text(encoding="utf-8").splitlines())
    card, index = docs / f"{args.name}.md", docs / "README.md"
    docs.mkdir(parents=True, exist_ok=True)
    existing = card.read_text(encoding="utf-8") if card.is_file() else None
    card.write_text(render(args.name, ev, args.run, preserved_notes(existing), labels), encoding="utf-8")
    status, _ = status_of(ev)
    previous = index.read_text(encoding="utf-8") if index.is_file() else None
    index.write_text(
        update_index(previous, args.name, index_row(args.name, ev.facts, status)), encoding="utf-8"
    )
    print(f"{card}: {status.value}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
