#!/usr/bin/env python3
"""Turn a survey's raw dumps into redacted fixtures, and read each one the way agent-phone will.
Run it from the repo root, after `survey.py` saved `probes/android/raw/<name>-<screen>.raw.xml`:

    uv run python -I .claude/skills/port-android-device/scripts/fixtures.py <run> <name> [--write-test]

For the launcher, Settings and the dialog it redacts the raw dump into `tests/fixtures/dumps/<name>-
<screen>.xml` with `probes/android/redact.py`, parses it with `parse_hierarchy` at the natural display
size of `<run>/facts.json`, and writes `<run>/fixtures.json`: the windows, the roots of another display,
the rotation, the display size, the active window, the other windows and `dialog`, as `select_surface`
computes it. It prints a table and exits 1 when a fixture is an anomaly (see `Rule`). With
`--write-test`, and only when there is none, it writes `tests/test_<name>_dumps.py`, which pins each
fixture's active package, `dialog` and other windows. It reads no phone.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))

from device_calls import REPO, device_name, run_folder  # noqa: E402
from surveyed_screens import Screen  # noqa: E402

from agent_phone.adapters.uiautomator2.parse import EDGE_SLACK, parse_hierarchy  # noqa: E402
from agent_phone.core.geometry import Size  # noqa: E402
from agent_phone.core.outcome import Refusal  # noqa: E402
from agent_phone.core.screen import WindowKind  # noqa: E402
from agent_phone.core.snapshot.surface import select_surface  # noqa: E402

REDACT = REPO / "probes" / "android" / "redact.py"
LABELS = REPO / "probes" / "android" / "ui_labels.txt"
PLACEHOLDER_ATTRS = ("text", "content-desc", "hint")


class Rule(Enum):
    """What makes a fixture an anomaly: the parser or the phone did something the tests do not expect."""

    NO_ACTIVE_WINDOW = "no_active_window"
    SYSTEM_WINDOW_ACTIVE = "system_window_active"
    DIALOG_ON_FULL_SCREEN = "dialog_on_full_screen"
    NO_DIALOG = "no_dialog"
    OUT_OF_BOUNDS = "out_of_bounds"


@dataclass(frozen=True, slots=True)
class Anomaly:
    screen: str
    rule: Rule
    detail: str


@dataclass(frozen=True, slots=True)
class WindowRow:
    package: str
    kind: str
    bounds: tuple[int, int, int, int]
    active: bool


@dataclass(frozen=True, slots=True)
class Reading:
    """`dialog` and `active` are None when the dump has no active window. `error` is set when the
    parser refused the dump, which leaves every other field empty."""

    windows: tuple[WindowRow, ...]
    other_display_roots: int
    rotation: int | None
    display: tuple[int, int] | None
    active: str | None
    dialog: bool | None
    others: tuple[str, ...]
    error: str | None = None


@dataclass(frozen=True, slots=True)
class Paths:
    raw: Path = REPO / "probes" / "android" / "raw"
    fixtures: Path = REPO / "tests" / "fixtures" / "dumps"
    tests: Path = REPO / "tests"


def roots_of_another_display(xml: str) -> int:
    return sum(1 for root in ET.fromstring(xml).findall("node") if root.get("display-id", "0") != "0")


def read_dump(xml: str, natural: Size) -> Reading:
    try:
        screen = parse_hierarchy(xml, natural, ime_package=None)
    except Refusal as refusal:
        return Reading((), 0, None, None, None, None, (), refusal.message)
    windows = tuple(
        WindowRow(
            w.package, w.kind.value, (w.bounds.left, w.bounds.top, w.bounds.right, w.bounds.bottom), w.active
        )
        for w in screen.windows
    )
    common = (
        windows,
        roots_of_another_display(xml),
        screen.rotation.value,
        (screen.display.width, screen.display.height),
    )
    try:
        surface = select_surface(screen)
    except Refusal:
        return Reading(*common, None, None, ())
    return Reading(*common, surface.window.package, surface.dialog, tuple(o.package for o in surface.others))


def anomalies(screen: Screen, reading: Reading) -> list[Anomaly]:
    found: list[Anomaly] = []

    def flag(rule: Rule, detail: str) -> None:
        found.append(Anomaly(screen.value, rule, detail))

    if reading.active is None:
        flag(Rule.NO_ACTIVE_WINDOW, reading.error or "no window could hold focus")
    active = next((w for w in reading.windows if w.active), None)
    if active and active.kind == WindowKind.SYSTEM.value:
        applications = [w.package for w in reading.windows if w.kind == WindowKind.APPLICATION.value]
        if applications:
            flag(
                Rule.SYSTEM_WINDOW_ACTIVE,
                f"{active.package} is active, and {', '.join(applications)} is open",
            )
    if screen.fills_the_display and reading.dialog is True:
        flag(Rule.DIALOG_ON_FULL_SCREEN, f"{reading.active} reads dialog: true")
    if not screen.fills_the_display and reading.dialog is False:
        flag(Rule.NO_DIALOG, f"{reading.active} reads dialog: false")
    if reading.display is not None:
        width, height = reading.display
        for window in reading.windows:
            left, top, right, bottom = window.bounds
            if min(left, top) < -EDGE_SLACK or right > width + EDGE_SLACK or bottom > height + EDGE_SLACK:
                flag(
                    Rule.OUT_OF_BOUNDS,
                    f"{window.package} {list(window.bounds)} on a {width}x{height} display",
                )
    return found


def unredacted(xml: str) -> list[str]:
    """The rule of `tests/test_fixtures_are_redacted.py`: a label that is not in `ui_labels.txt` is a
    `redacted-N` placeholder."""
    labels = set(LABELS.read_text().splitlines())
    values = (node.get(attr) for node in ET.fromstring(xml).iter("node") for attr in PLACEHOLDER_ATTRS)
    return [v for v in values if v and v not in labels and not v.startswith("redacted-")]


def redact(raw: Path, out: Path) -> None:
    done = subprocess.run(
        [sys.executable, "-I", str(REDACT), str(raw), str(out)], capture_output=True, text=True
    )
    if done.returncode != 0:
        sys.exit(f"fixtures: redact.py failed on {raw}: {done.stderr.strip()}")
    if unredacted(out.read_text()):
        out.unlink()
        sys.exit(f"fixtures: {out.name} still holds values that are not labels. It was deleted.")


def natural_size(facts: dict) -> Size:
    display = next((d for d in facts.get("displays", []) if d.get("id") == 0), None)
    if display is None:
        sys.exit("fixtures: facts.json names no display 0. Run facts.py again.")
    return Size(display["width"], display["height"])


def render_test(name: str, natural: Size, pinned: list[tuple[str, str, bool, tuple[str, ...]]]) -> str:
    def quoted(words: tuple[str, ...]) -> str:
        return "(" + ", ".join(json.dumps(word) for word in words) + ("," if len(words) == 1 else "") + ")"

    rows = "".join(
        f"    ({json.dumps(dump)}, {json.dumps(active)}, {dialog}, {quoted(others)}),\n"
        for dump, active, dialog, others in pinned
    )
    return f'''"""The {name} dumps: the active window, the dialog flag and the other windows of each, as
`fixtures.py` read them. A fixture's labels are placeholders, so these tests name no label."""

import pytest
from support import fixture_xml

from agent_phone.adapters.uiautomator2.parse import parse_hierarchy
from agent_phone.core.geometry import Size
from agent_phone.core.snapshot.surface import select_surface

NATURAL = Size({natural.width}, {natural.height})
PINNED = [
{rows}]


@pytest.mark.parametrize(("dump", "active", "dialog", "others"), PINNED)
def test_the_{name.replace("-", "_")}_dump_reads_as_pinned(dump, active, dialog, others):
    surface = select_surface(parse_hierarchy(fixture_xml(dump), NATURAL, ime_package=None))
    assert surface.window.package == active
    assert surface.dialog is dialog
    assert tuple(other.package for other in surface.others) == others
'''


HEAD = ("screen", "active", "dialog", "windows", "other display", "rot", "display")
WIDTHS = (9, 30, 7, 8, 14, 4, 10)


def line(cells: tuple[object, ...], last: str) -> str:
    return " ".join(f"{cell!s:<{width}}" for cell, width in zip(cells, WIDTHS, strict=True)) + f" {last}"


def table(readings: dict[Screen, Reading], found: list[Anomaly]) -> list[str]:
    rows = [line(HEAD, "anomalies")]
    for screen, r in readings.items():
        flagged = ",".join(a.rule.value for a in found if a.screen == screen.value) or "-"
        size = "x".join(map(str, r.display)) if r.display else "?"
        rotation = "?" if r.rotation is None else r.rotation
        cells = (
            screen.value,
            r.active or "-",
            r.dialog,
            len(r.windows),
            r.other_display_roots,
            rotation,
            size,
        )
        rows.append(line(cells, flagged))
    return rows


def build(paths: Paths, name: str, facts: dict) -> tuple[dict[Screen, Reading], list[Screen]]:
    """Redact and read every screen that has a raw dump. Returns the readings and the screens with none."""
    natural, readings, missing = natural_size(facts), {}, []
    paths.fixtures.mkdir(parents=True, exist_ok=True)
    for screen in Screen:
        raw = paths.raw / f"{name}-{screen.value}.raw.xml"
        if not raw.is_file():
            missing.append(screen)
            continue
        out = paths.fixtures / f"{name}-{screen.value}.xml"
        redact(raw, out)
        readings[screen] = read_dump(out.read_text(), natural)
    return readings, missing


def main(argv: list[str], paths: Paths | None = None) -> int:
    paths = paths or Paths()
    parser = argparse.ArgumentParser(prog="fixtures.py", description="Redact a survey's dumps into fixtures.")
    parser.add_argument("run", type=run_folder)
    parser.add_argument("name", type=device_name)
    parser.add_argument(
        "--write-test", action="store_true", help="pin the fixtures in tests/test_<name>_dumps.py"
    )
    args = parser.parse_args(argv)
    try:
        facts = json.loads((args.run / "facts.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        sys.exit(f"fixtures: {args.run}/facts.json is missing or not JSON. Run facts.py first.")
    readings, missing = build(paths, args.name, facts)
    if not readings:
        sys.exit(f"fixtures: no raw dump named {args.name}-<screen> in {paths.raw}. Run survey.py first.")
    found = [a for screen, reading in readings.items() for a in anomalies(screen, reading)]
    document = {
        "name": args.name,
        "screens": {screen.value: asdict(reading) for screen, reading in readings.items()},
        "missing": [screen.value for screen in missing],
        "anomalies": [{"screen": a.screen, "rule": a.rule.value, "detail": a.detail} for a in found],
    }
    (args.run / "fixtures.json").write_text(
        json.dumps(document, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print("\n".join(table(readings, found)))
    for screen in missing:
        print(f"note: no raw dump of the {screen.value}, so no fixture of it")
    for a in found:
        print(f"anomaly {a.screen}: {a.rule.value}: {a.detail}")
    if args.write_test and not found:
        pinned = [
            (f"{args.name}-{screen.value}", r.active, r.dialog, r.others) for screen, r in readings.items()
        ]
        target = paths.tests / f"test_{args.name.replace('-', '_')}_dumps.py"
        target.write_text(render_test(args.name, natural_size(facts), pinned), encoding="utf-8")
        print(f"wrote {target}")
    elif args.write_test:
        print("no test written: fix the anomalies, or explain them, first")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
