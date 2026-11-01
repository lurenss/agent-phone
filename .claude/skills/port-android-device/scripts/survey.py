#!/usr/bin/env python3
"""Done-when 4 of docs/plan.md on any device, plus raw dumps and an input journey. Run it from the
repo root, with a run folder from the verify skill and the `facts.json` that `facts.py` wrote:

    uv run python -I .claude/skills/port-android-device/scripts/survey.py <run> <serial> <name>

It writes `<run>/survey.jsonl`, one JSON line per check as `probes/android/unit7_probe.py` does, and
prints the same lines. Every call goes through `evidence.py`. The inputs are the ones in `journey`
and no others, and never a tap: home, Settings by intent, the system's Bluetooth request (it only
asks, and back declines it), back, the About-phone page by intent, a scroll down and up that proves
swipes, back, home. Before each input it reads the screen, because agent-phone refuses an input
without a fresh observation (`OBSERVE_FIRST`).

A scroll names its target: the ref of the collection with the largest area in the read just before
it. A scroll with no target is `AMBIGUOUS_TARGET` when two elements scroll, as on Android 15's
About-phone page. A read with no collection skips the scroll and writes an `input` line with
`skipped`.

For the launcher, Settings and the dialog it takes one settled read, checks it against the app that
`dumpsys window displays` names for display 0, saves a raw dump as `probes/android/raw/<name>-<screen>
.raw.xml` for `fixtures.py`, and times 20 snapshots and 10 settled snapshots.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))

from device_calls import (  # noqa: E402
    Call,
    EvidenceRefused,
    Journal,
    ObserveFailed,
    Recorder,
    Runner,
    device_name,
    run_folder,
)
from device_reads import parse_window_displays  # noqa: E402
from surveyed_screens import Screen  # noqa: E402

SETTINGS = "intent:#Intent;action=android.settings.SETTINGS;end"
ABOUT = "intent:#Intent;action=android.settings.DEVICE_INFO_SETTINGS;end"
BLUETOOTH = "intent:#Intent;action=android.bluetooth.adapter.action.{}"
RUNS, SETTLES, BUDGET = 20, 10, 8 * 1024
REF = re.compile(r"@\w+:e\d+ ")
COLLECTION = re.compile(r"\s*(@\w+:e\d+) (?:scroll|list|grid|pager)\b")
BOUNDS = re.compile(r"\[(-?\d+),(-?\d+),(-?\d+),(-?\d+)\]$")
NO_SCROLLER = "no scrolling element"


@dataclass(frozen=True, slots=True)
class Step:
    """One input, and the screen it should show, when it is one of the three that are surveyed."""

    name: str
    words: tuple[str, ...]
    shows: Screen | None = None

    @property
    def scrolls(self) -> bool:
        return self.words[0] == "scroll"


def journey(bluetooth_on: bool | None) -> tuple[Step, ...]:
    """The only inputs of the survey, in order. Bluetooth off is asked to turn on, and Bluetooth on
    is asked to be discoverable: either dialog only asks, and back declines it."""
    action = "REQUEST_DISCOVERABLE" if bluetooth_on else "REQUEST_ENABLE"
    return (
        Step("home", ("press", "home"), Screen.LAUNCHER),
        Step("open settings", ("open-url", SETTINGS), Screen.SETTINGS),
        Step("open dialog", ("open-url", BLUETOOTH.format(action) + ";end"), Screen.DIALOG),
        Step("back from the dialog", ("press", "back")),
        Step("open about", ("open-url", ABOUT)),
        Step("scroll down", ("scroll", "down")),
        Step("scroll up", ("scroll", "up")),
        Step("back from about", ("press", "back")),
        Step("home again", ("press", "home")),
    )


@dataclass(frozen=True, slots=True)
class Seen:
    """One read of the screen. A read that failed has no app."""

    call: Call

    @property
    def app(self) -> str | None:
        return self.call.data.get("app")

    @property
    def dialog(self) -> bool | None:
        return self.call.data.get("dialog")

    @property
    def shape(self) -> tuple[str, ...]:
        """The tree without its refs, which change with every read."""
        return tuple(REF.sub("", line) for line in self.call.data.get("tree", []))


def area(line: str) -> int:
    bounds = BOUNDS.search(line)
    if bounds is None:
        return 0
    left, top, right, bottom = map(int, bounds.groups())
    return (right - left) * (bottom - top)


def scroll_target(seen: Seen) -> str | None:
    """The ref of the collection with the largest area on the read, or the first of two that tie."""
    found = [(area(line), m[1]) for line in seen.call.data.get("tree", []) if (m := COLLECTION.match(line))]
    return max(found, key=lambda item: item[0])[1] if found else None


def read_screen(rec: Recorder, label: str) -> Seen:
    return Seen(rec.read(label, "snapshot", "--settle"))


def focus_app(rec: Recorder, label: str) -> str | None:
    """The app `dumpsys window displays` names for display 0: a read agent-phone did not make."""
    text = rec.adb(label, "shell", "dumpsys", "window", "displays").text
    return parse_window_displays(text).owners.get(0)


@dataclass(frozen=True, slots=True)
class Capture:
    seen: Seen
    focus: str | None
    reads: int
    shown: bool

    @property
    def agrees(self) -> bool | None:
        return None if self.focus is None or self.seen.app is None else self.focus == self.seen.app


def capture(rec: Recorder, screen: Screen, tries: int, intended: Callable[[Seen], bool]) -> Capture:
    """Read until a read is the screen asked for and agrees with the focus, at most `tries` times. A
    read that is the screen but never agrees is kept with `agrees` false, because that disagreement
    is a finding. When no read is the screen, the last one is kept with `shown` false."""
    kept = None
    for reads in range(1, tries + 1):
        seen = read_screen(rec, f"{screen.value}-settled")
        taken = Capture(seen, focus_app(rec, f"{screen.value}-focus"), reads, seen.call.ok and intended(seen))
        if kept is None or taken.shown or not kept.shown:
            kept = taken
        if taken.shown and taken.agrees is not False:
            break
    assert kept is not None
    return kept


def acceptance(screen: Screen, launcher_app: str | None) -> tuple[int, Callable[[Seen], bool]]:
    """How many reads a screen gets, and what makes a read that screen. The dialog counts as shown
    when a settled read says `dialog: true`. Settings is any app but the launcher. The launcher is
    whatever home shows: its package is recorded, not assumed."""
    match screen:
        case Screen.DIALOG:
            return 10, lambda seen: seen.dialog is True
        case Screen.SETTINGS:
            return 3, lambda seen: seen.app != launcher_app
        case Screen.LAUNCHER:
            return 3, lambda seen: True


def summarize(calls: list[Call], expected: Seen) -> dict:
    """One `warm_snapshot` line: a read is wrong when it is ok and shows another app or dialog flag."""
    wrong = sum(
        c.ok and not (c.data.get("app") == expected.app and c.data.get("dialog") is expected.dialog)
        for c in calls
    )
    sizes = [c.stdout_bytes for c in calls]
    lines = [len(c.data.get("tree", [])) for c in calls]
    times = [c.ms for c in calls]
    return {
        "runs": len(calls),
        "errors": sum(not c.ok for c in calls),
        "wrong_screen": wrong,
        "median_ms": round(statistics.median(times)),
        "range_ms": [min(times), max(times)],
        "bytes": [min(sizes), max(sizes)],
        "under_8_kb": max(sizes) < BUDGET,
        "tree_lines": [min(lines), max(lines)],
    }


def bench(rec: Recorder, journal: Journal, screen: Screen, expected: Seen) -> None:
    plain = [rec.read(f"{screen.value}-snap-{i}", "snapshot") for i in range(RUNS)]
    settle = [rec.read(f"{screen.value}-settle-{i}", "snapshot", "--settle") for i in range(SETTLES)]
    journal.emit(check="warm_snapshot", screen=screen.value, **summarize(plain, expected))
    journal.emit(
        check="warm_settle",
        screen=screen.value,
        settled=sum(c.data.get("settled") == "settled" for c in settle),
        runs=SETTLES,
        median_ms=round(statistics.median(c.ms for c in settle)),
    )


def record_screen(rec: Recorder, journal: Journal, name: str, screen: Screen, got: Capture) -> None:
    if not got.shown:
        journal.emit(
            check=f"{screen.value}_not_shown",
            reads=got.reads,
            app=got.seen.app,
            dialog=got.seen.dialog,
            focus_app=got.focus,
        )
        return
    call = got.seen.call
    journal.emit(
        check="screen_read",
        screen=screen.value,
        app=got.seen.app,
        window=call.data.get("window"),
        dialog=got.seen.dialog,
        settled=call.data.get("settled"),
        lines=len(call.data.get("tree", [])),
        focus_app=got.focus,
        agrees=got.agrees,
        reads=got.reads,
    )
    dump = rec.raw_dump(f"{screen.value}-dump", f"{name}-{screen.value}")
    journal.emit(
        check="raw_dump", screen=screen.value, file=f"{name}-{screen.value}", ok=dump.record["exit"] == 0
    )
    bench(rec, journal, screen, got.seen)


def survey(rec: Recorder, journal: Journal, facts: dict, name: str) -> None:
    previous = Seen(rec.look("start"))
    launcher_app = None
    for number, step in enumerate(journey(facts.get("bluetooth_on")), 1):
        words = step.words
        if step.scrolls:
            if not rec.fresh:
                previous = Seen(rec.look(f"before-{number}"))
            if (target := scroll_target(previous)) is None:
                journal.emit(
                    check="input",
                    step=number,
                    name=step.name,
                    argv=list(step.words),
                    delivery=None,
                    verified_by=None,
                    error=None,
                    after_app=previous.app,
                    after_dialog=previous.dialog,
                    changed=None,
                    skipped=NO_SCROLLER,
                )
                continue
            words = (*step.words, target)
        sent = rec.send(f"step-{number}", *words)
        if step.shows is None:
            got = Capture(read_screen(rec, f"after-{number}"), None, 1, True)
        else:
            tries, accepts = acceptance(step.shows, launcher_app)
            got = capture(rec, step.shows, tries, accepts)
        changed = got.seen.shape != previous.shape if got.seen.call.ok else None
        journal.emit(
            check="input",
            step=number,
            name=step.name,
            argv=list(step.words),
            delivery=sent.delivery,
            verified_by=sent.verified_by,
            error=sent.error_code,
            after_app=got.seen.app,
            after_dialog=got.seen.dialog,
            changed=changed,
        )
        if step.shows is not None:
            record_screen(rec, journal, name, step.shows, got)
            if step.shows is Screen.LAUNCHER and got.shown:
                launcher_app = got.seen.app
        if got.seen.call.ok:
            previous = got.seen
    journal.emit(check="inputs", sent=rec.sent)


def main(argv: list[str], runner: Runner = subprocess.run) -> int:
    parser = argparse.ArgumentParser(prog="survey.py", description="Survey a phone's screens and inputs.")
    parser.add_argument("run", type=run_folder)
    parser.add_argument("serial")
    parser.add_argument("name", type=device_name)
    args = parser.parse_args(argv)
    try:
        facts = json.loads((args.run / "facts.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        sys.exit(f"survey: {args.run}/facts.json is missing or not JSON. Run facts.py first.")
    if facts.get("serial") != args.serial:
        sys.exit(f"survey: facts.json is for {facts.get('serial')}, not {args.serial}.")
    if facts.get("awake") is False:
        sys.exit("survey: the screen is off. Waking the phone is an input, so ask the phone's owner.")
    rec, journal = Recorder(args.run, args.serial, runner), Journal(args.run / "survey.jsonl")
    try:
        survey(rec, journal, facts, args.name)
    except (ObserveFailed, EvidenceRefused) as stop:
        journal.emit(check="aborted", reason=str(stop), sent=rec.sent)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
