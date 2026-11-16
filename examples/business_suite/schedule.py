"""Schedule a reel in Meta Business Suite through agent-phone's public API only (plan unit 8).

A consumer, not part of the framework: everything app-specific is here or in `policy.toml`
next to it. Each `wait_for` replaces a fixed sleep of the old `mbs_schedule.py`, and each one
also records the observation that the next step's OBSERVE_FIRST check needs.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agent_phone import Driver, Effect, Gone, KeyName, Match, Present, Q, Role, Settled, open_phone

PACKAGE = "com.facebook.pages.app"
POLICY = Path(__file__).with_name("policy.toml")
# The field's name is its hint, which Business Suite has made longer before.
CAPTION = Q("Describe your reel", match=Match.PREFIX, role=Role.TEXT_FIELD)
HOME = Q("Create new post")


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
    if phone.count(HOME) == 0:
        phone.launch(PACKAGE, wait_for=Present(HOME))
    sheet = phone.click(HOME, wait_for=Present(Q("Create new content"))).after
    assert sheet is not None
    reel = sheet.pick(Q("Reel", role=Role.BUTTON), below=Q("Create new content"))
    phone.click(reel, wait_for=Present(Q("Create reel with Video, item 1", match=Match.PREFIX)))
    phone.click(Q("Create reel with Video, item 1", match=Match.PREFIX), wait_for=Present(Q("Next")))
    phone.click(Q("Next"), wait_for=Present(CAPTION))
    phone.set_text(CAPTION, caption)
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
    """Type the time, because the numbers on the clock face take no tap. Seen on the phone: OK in
    the typing mode sits in a view whose id, `input_block`, the default policy reads as blocking a
    person, so the picker goes back to the clock face, where AM and PM are buttons, before OK."""
    typing, clock_face = (
        Q("Switch to text input mode", match=Match.PREFIX),
        Q("Switch to clock mode", match=Match.PREFIX),
    )
    phone.click(Q(value=":", match=Match.CONTAINS, role=Role.TEXT_FIELD), wait_for=Present(typing))
    phone.click(typing, wait_for=Present(Q(id="input_hour")))
    phone.set_text(Q(id="input_hour"), str(at.hour12))
    phone.set_text(Q(id="input_minute"), f"{at.minute:02d}")
    phone.click(clock_face, wait_for=Present(Q(at.ampm, role=Role.RADIO)))
    phone.click(Q(at.ampm, role=Role.RADIO), wait_for=Settled())
    phone.click(Q("OK"), wait_for=Present(Q(value=f"{at.hour12}:{at.minute:02d} {at.ampm}")))


def _leave_composer(phone: Driver) -> None:
    """Back out to Home without keeping a draft, in at most six steps, looking before each one. Seen
    on the phone: BACK goes from the caption page to the reel editor and from there to the gallery
    picker, whose Cancel ends on Home."""
    for _ in range(6):
        buttons = [line.name for line in phone.snapshot().lines if line.role is Role.BUTTON]
        discard = next((name for name in buttons if name.startswith("Discard")), None)
        if "Create new post" in buttons:
            return
        if discard is not None:
            phone.click(Q(discard, role=Role.BUTTON), commit=Effect.DELETE, wait_for=Settled())
        elif "Cancel" in buttons:
            phone.click(Q("Cancel", role=Role.BUTTON), wait_for=Settled())
        else:
            phone.press(KeyName.BACK, wait_for=Settled())
    raise LookupError("Business Suite is still in the composer after six steps back")
