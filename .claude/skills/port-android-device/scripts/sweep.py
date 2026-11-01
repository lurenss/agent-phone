#!/usr/bin/env python3
"""Open each app on a phone and say what the gate would make of its screen. Run it from the repo
root, with a run folder from the verify skill and the `facts.json` that `facts.py` wrote:

    uv run python -I .claude/skills/port-android-device/scripts/sweep.py <run> <serial> <package>...

For each package it launches the app, waits for a settled screen with a button on it (20 s at most),
reads the snapshot, saves a raw dump as `probes/android/raw/sweep-<serial>-<package>.raw.xml`, judges
every element of the app's window that takes a tap with `probes/android/gate_check.py`'s `judge`, and
presses home. The policy is the default, plus the profile installed for the serial in the state root.
The only inputs are the launch and home. It never taps inside an app. A package that evidence.py
refuses, such as a protected one, is skipped.

It writes `<run>/apps.jsonl`, one line per package: how the launch and the wait went, the settled
time, whether the snapshot had any lines (a game or a canvas has none), and the counts of clear,
commits by effect, denied and refused targets, with up to 8 sample labels for each effect. The
labels come from the screen and can be private, so the file stays in the run folder.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))
sys.path.append(str(Path(__file__).resolve().parents[4] / "probes" / "android"))

import gate_check  # noqa: E402
from device_calls import REPO, EvidenceRefused, Journal, ObserveFailed, Recorder, Runner, run_folder  # noqa: E402

from agent_phone.adapters.uiautomator2.parse import parse_hierarchy  # noqa: E402
from agent_phone.cli.policy import load_policy, load_profiles, profile_for  # noqa: E402
from agent_phone.cli.settings import Settings  # noqa: E402
from agent_phone.core.device import Serial  # noqa: E402
from agent_phone.core.geometry import Size  # noqa: E402
from agent_phone.core.outcome import Refusal  # noqa: E402
from agent_phone.core.phone import NAME as PACKAGE_NAME  # noqa: E402
from agent_phone.core.policy.engine import Clear, Commits, Denied  # noqa: E402
from agent_phone.core.policy.rules import Policy  # noqa: E402

SAMPLES = 8
WAIT_MS = 20_000
RAW = REPO / "probes" / "android" / "raw"


def package_name(text: str) -> str:
    if not PACKAGE_NAME.fullmatch(text):
        raise argparse.ArgumentTypeError(f"{text!r} is not a package name as pm list packages prints one")
    return text


@dataclass(frozen=True, slots=True)
class Tally:
    """What the gate said about each target of one screen. A target that commits two effects is in
    both effects' counts and once in `targets`."""

    targets: int
    clear: int
    commits: dict[str, int]
    denied: int
    refused: dict[str, int]
    samples: dict[str, list[str]]


def tally(judged: Iterable[gate_check.Judged]) -> Tally:
    clear, denied, targets = 0, 0, 0
    commits: Counter[str] = Counter()
    refused: Counter[str] = Counter()
    seen: dict[str, list[str]] = {}

    def sample(kind: str, name: str) -> None:
        names = seen.setdefault(kind, [])
        if name and name not in names and len(names) < SAMPLES:
            names.append(name)

    for item in judged:
        targets += 1
        match item.outcome:
            case Clear():
                clear += 1
            case Commits(effects=effects):
                for effect in sorted(e.value for e in effects):
                    commits[effect] += 1
                    sample(effect, item.name)
            case Denied():
                denied += 1
                sample("denied", item.name)
            case Refusal() as refusal:
                refused[refusal.code.value] += 1
    return Tally(targets, clear, dict(commits), denied, dict(refused), seen)


@dataclass(frozen=True, slots=True)
class Sweep:
    """What every package of a sweep shares: the recorder, the journal, how its dump is read and the
    policy that judges it."""

    rec: Recorder
    journal: Journal
    raw_dir: Path
    natural: Size
    locale: str
    policy: Policy
    profile: str | None


def counts(sweep: Sweep, app: str, raw: Path) -> dict:
    """The gate's counts for the taps the app's own window could take, from its raw dump."""
    screen = parse_hierarchy(raw.read_text(encoding="utf-8"), sweep.natural, ime_package=None)
    found = tally(j for j in gate_check.judge(screen, sweep.policy, sweep.locale) if j.package == app)
    return {
        "targets": found.targets,
        "clear": found.clear,
        "commits": found.commits,
        "denied": found.denied,
        "refused": sum(found.refused.values()),
        "refused_codes": found.refused,
        "samples": found.samples,
    }


def sweep_one(sweep: Sweep, package: str) -> None:
    rec = sweep.rec
    line: dict = {"package": package, "launched": False, "profile": sweep.profile}
    try:
        launched = rec.send(f"launch-{package}", "launch", package)
    except EvidenceRefused as refused:
        sweep.journal.emit(**line, skipped=str(refused))
        return
    line |= {"delivery": launched.delivery, "launch_error": launched.error_code}
    if launched.error_code is not None and launched.delivery == "not_delivered":
        sweep.journal.emit(**line)
        return
    line["launched"] = True
    waited = rec.read(
        f"wait-{package}",
        "wait",
        "--app",
        package,
        "--settled",
        "--for",
        "role=button",
        "--timeout-ms",
        str(WAIT_MS),
    )
    line |= {
        "wait_ok": waited.ok,
        "wait_error": waited.error_code,
        "settled_ms": waited.ms if waited.ok else None,
    }
    looked = rec.read(f"snapshot-{package}", "snapshot")
    tree = looked.data.get("tree", [])
    shown = looked.data.get("app")
    line |= {"app_shown": shown, "snapshot_lines": len(tree), "has_lines": bool(tree)}
    label = f"sweep-{re.sub(r'[^A-Za-z0-9._-]', '-', rec.serial)}-{package}"
    dump = rec.raw_dump(f"dump-{package}", label)
    raw = sweep.raw_dir / f"{label}.raw.xml"
    if shown != package:
        line["error"] = "not_foreground"
    elif dump.record["exit"] != 0 or not raw.is_file():
        line["error"] = "no_dump"
    else:
        line |= counts(sweep, package, raw)
    sweep.journal.emit(**line)
    rec.send(f"home-{package}", "press", "home")


def installed_policy(serial: str) -> tuple[Policy, str | None]:
    """The default policy and the profile installed for the serial, as agent-phone loads them."""
    try:
        profile = profile_for(load_profiles(Settings.from_environment().state_root), Serial(serial))
        return load_policy([], profile), profile.profile.name if profile else None
    except Refusal as refusal:
        sys.exit(f"sweep: agent-phone refuses the installed profiles: {refusal.message}")


def main(argv: list[str], runner: Runner = subprocess.run, raw_dir: Path = RAW) -> int:
    parser = argparse.ArgumentParser(prog="sweep.py", description="Open each app and judge its taps.")
    parser.add_argument("run", type=run_folder)
    parser.add_argument("serial")
    parser.add_argument("package", nargs="+", type=package_name)
    args = parser.parse_args(argv)
    try:
        facts = json.loads((args.run / "facts.json").read_text(encoding="utf-8"))
        display = next(d for d in facts["displays"] if d["id"] == 0)
        natural, locale = Size(display["width"], display["height"]), facts["locale"] or ""
    except (OSError, ValueError, KeyError, StopIteration):
        locale = ""
    if not locale:
        sys.exit(
            f"sweep: {args.run}/facts.json is missing, or has no locale or no display 0. Run facts.py first."
        )
    policy, profile = installed_policy(args.serial)
    rec, journal = Recorder(args.run, args.serial, runner), Journal(args.run / "apps.jsonl")
    sweep = Sweep(rec, journal, raw_dir, natural, locale, policy, profile)
    for package in args.package:
        try:
            sweep_one(sweep, package)
        except ObserveFailed as stop:
            journal.emit(package=package, launched=False, aborted=str(stop))
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
