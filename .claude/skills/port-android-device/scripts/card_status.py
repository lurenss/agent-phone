"""What a device's survey, fixtures and sweep add up to: whether it passes done-when 4, and one of
three statuses. Pure functions on the parsed files, so the rules are tested on canned lines.

Done-when 4 (docs/plan.md) on Settings and the system dialog: no snapshot failed or showed another
screen, the median is under 400 ms, no output reaches 8 KB, and every settled read settled.

The status, in order:

- `blocked` when agent-phone cannot read or drive the phone: the survey stopped, the launcher was never
  read, every snapshot of a measured screen failed, or a key press (home, back) came back with an error.
- `works with limits` when it can, and any of these holds: done-when 4 is not met, the dialog or
  Settings was never shown, an input other than a key press failed, a back key changed no screen, a
  scroll failed, was skipped or moved nothing, a settled read named another app than the focus did, a
  fixture is an anomaly, the policy has no rules for the language, the phone has a second display, or
  keys go to another display than 0.
- `works` otherwise.

A sweep does not change the status: what an app shows is that app's, not the device's.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

MEDIAN_MS = 400
BUDGET_BYTES = 8 * 1024
MEASURED = ("settings", "dialog")
KEYS = ("home", "back from the dialog", "back from about", "home again")
BACKS = ("back from the dialog", "back from about")
SCROLLS = ("scroll down", "scroll up")


class Status(Enum):
    WORKS = "works"
    LIMITS = "works with limits"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class Evidence:
    """The four files of a run, parsed. `fixtures` is None and `apps` is empty when that step did not run."""

    facts: dict
    survey: tuple[dict, ...]
    fixtures: dict | None = None
    apps: tuple[dict, ...] = ()

    def checks(self, name: str) -> list[dict]:
        return [line for line in self.survey if line.get("check") == name]

    def of_screen(self, name: str, screen: str) -> dict | None:
        return next((line for line in self.checks(name) if line.get("screen") == screen), None)

    def step(self, name: str) -> dict | None:
        return next((line for line in self.checks("input") if line.get("name") == name), None)


def done_when_4(ev: Evidence) -> list[str]:
    """Why done-when 4 is not met, one sentence each. An empty list means it is met."""
    failures = []
    for screen in MEASURED:
        warm, settle = ev.of_screen("warm_snapshot", screen), ev.of_screen("warm_settle", screen)
        if warm is None:
            failures.append(f"The {screen} was not measured.")
            continue
        if warm["errors"]:
            failures.append(f"{warm['errors']} of {warm['runs']} snapshots of the {screen} failed.")
        if warm["wrong_screen"]:
            failures.append(f"{warm['wrong_screen']} snapshots of the {screen} showed another screen.")
        if warm["median_ms"] >= MEDIAN_MS:
            failures.append(
                f"The median snapshot of the {screen} took {warm['median_ms']} ms, not under {MEDIAN_MS}."
            )
        if warm["bytes"][1] >= BUDGET_BYTES:
            failures.append(
                f"A snapshot of the {screen} was {warm['bytes'][1]} bytes, not under {BUDGET_BYTES}."
            )
        if settle and settle["settled"] < settle["runs"]:
            failures.append(
                f"{settle['settled']} of {settle['runs']} settled snapshots of the {screen} settled."
            )
    return failures


def blockers(ev: Evidence) -> list[str]:
    found = [f"The survey stopped: {line.get('reason')}." for line in ev.checks("aborted")]
    if ev.checks("launcher_not_shown"):
        found.append("The launcher was never read.")
    for screen in ("launcher", *MEASURED):
        warm = ev.of_screen("warm_snapshot", screen)
        if warm and warm["errors"] == warm["runs"]:
            found.append(f"Every snapshot of the {screen} failed.")
    for name in KEYS:
        step = ev.step(name)
        if step and step.get("error"):
            found.append(f"The key press '{name}' failed with {step['error']}.")
    return found


def limits(ev: Evidence) -> list[str]:
    found = list(done_when_4(ev))
    for screen in ("settings", "dialog"):
        if ev.checks(f"{screen}_not_shown"):
            found.append(f"The {screen} was never shown.")
    for step in ev.checks("input"):
        if step.get("error") and step["name"] not in KEYS:
            found.append(f"The input '{step['name']}' failed with {step['error']}.")
    for name in BACKS:
        step = ev.step(name)
        if step and not step.get("error") and step.get("changed") is False:
            found.append(f"The key press '{name}' changed no screen.")
    for name in SCROLLS:
        step = ev.step(name)
        if step and step.get("skipped"):
            found.append(f"The input '{name}' was skipped: {step['skipped']}.")
        if step and not step.get("error") and step.get("changed") is False:
            found.append(f"The input '{name}' moved nothing.")
    for read in ev.checks("screen_read"):
        if read.get("agrees") is False:
            named = f"the settled read named {read['app']} and the focus named {read['focus_app']}"
            found.append(f"On the {read['screen']}, {named}.")
    for anomaly in (ev.fixtures or {}).get("anomalies", []):
        found.append(
            f"The {anomaly['screen']} fixture is an anomaly ({anomaly['rule']}): {anomaly['detail']}."
        )
    facts = ev.facts
    if facts.get("language_covered") is False:
        found.append(f"The policy has no rules for the language {facts.get('language')}.")
    if len(facts.get("displays", [])) > 1:
        found.append("The phone has more than one display. Only display 0 is read and tapped.")
    if facts.get("top_focused_display") not in (None, 0):
        found.append(f"Keys go to display {facts['top_focused_display']}, not display 0.")
    return found


def status_of(ev: Evidence) -> tuple[Status, list[str]]:
    """The status and every reason it is not `works`. A blocked device lists its blockers first."""
    stopped = blockers(ev)
    reasons = [*stopped, *limits(ev)]
    if stopped:
        return Status.BLOCKED, reasons
    return (Status.LIMITS if reasons else Status.WORKS), reasons
