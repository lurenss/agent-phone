"""Schedule a reel in Meta Business Suite through agent-phone's public API only (plan unit 8).

A consumer, not part of the framework: everything app-specific is here or in `policy.toml`
next to it. Each `wait_for` replaces a fixed sleep of the old `mbs_schedule.py`, and each one
also records the observation that the next step's OBSERVE_FIRST check needs.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agent_phone import Driver, Effect, Gone, Match, Present, Q, Role, open_phone

PACKAGE = "com.facebook.pages.app"
POLICY = Path(__file__).with_name("policy.toml")


@dataclass(frozen=True)
class PhoneTime:
    day_label: str
    hour12: int
    minute: int
    ampm: str


def schedule_reel(serial: str | None, caption: str, at: PhoneTime, dry_run: bool) -> str:
    with open_phone(serial, policies=[POLICY]) as phone:
        return _flow(phone, caption, at, dry_run)


def _flow(phone: Driver, caption: str, at: PhoneTime, dry_run: bool) -> str:
    phone.launch(PACKAGE, wait_for=Present(Q("Create new post")))
    sheet = phone.click(Q("Create new post"), wait_for=Present(Q("Create new content"))).after
    assert sheet is not None
    reel = sheet.pick(Q("Reel", role=Role.BUTTON), below=Q("Create new content"))
    phone.click(reel, wait_for=Present(Q("Create reel with Video, item 1", match=Match.PREFIX)))
    phone.click(Q("Create reel with Video, item 1", match=Match.PREFIX), wait_for=Present(Q("Next")))
    phone.click(Q("Next"), wait_for=Present(Q("Describe your reel", role=Role.TEXT_FIELD)))
    phone.set_text(Q("Describe your reel", role=Role.TEXT_FIELD), caption)
    phone.click(Q("Schedule for later"), wait_for=Present(Q("SCHEDULE")))
    _set_time(phone, at)
    if dry_run:
        phone.click(Q("CANCEL"), wait_for=Gone(Q("SCHEDULE")))
        _leave_composer(phone)
        return "dry_run"
    phone.click(Q("SCHEDULE"), commit=Effect.SCHEDULE, wait_for=Present(Q("Schedule reel")))
    done = phone.click(Q("Schedule reel"), commit=Effect.SCHEDULE, wait_for=Gone(Q("Schedule reel")))
    return done.disposition.value


def _set_time(phone: Driver, at: PhoneTime) -> None:
    clock = phone.snapshot().pick(Q(":", match=Match.CONTAINS, role=Role.BUTTON))
    phone.click(clock, wait_for=Present(Q(str(at.hour12))))
    phone.click(Q(str(at.hour12)), wait_for=Present(Q(f"{at.minute:02d}")))
    phone.click(Q(f"{at.minute:02d}"), wait_for=Present(Q(at.ampm)))
    phone.click(Q(at.ampm), wait_for=Present(Q("OK")))
    phone.click(Q("OK"), wait_for=Present(Q(f"{at.hour12}:{at.minute:02d} {at.ampm}")))


def _leave_composer(phone: Driver) -> None:
    # TODO: up to 6 rounds: snapshot; "Create new post" present -> done; "Discard" present ->
    # click(commit=Effect.DELETE); "Cancel" present -> click; else press(BACK, wait_for=Settled())
    raise NotImplementedError
