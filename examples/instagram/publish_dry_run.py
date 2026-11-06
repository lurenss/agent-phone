"""The steps before Share of the old `publish_reel.py --dry-run`, on agent-phone's public API.

A consumer, not part of the framework: everything Instagram knows is here. For each account it
opens the profile, switches to the account if another one is active, opens a new reel, picks the
clip whose length matches the file, writes the caption, then backs out with Start over and closes
the picker. It never taps Share, and the gate would refuse it without `--commit publish` anyway
(`probes/android/gate_check.py` on the composer's dump says `commits publish`).

    uv run python examples/instagram/publish_dry_run.py SERIAL FILE CAPTION --accounts FIRST,SECOND [--cold]

`--cold` force-stops Instagram first and starts it again, as the old script does. Each account ends
with no pending session, and `--clear-only` does only that. Every step
prints its time, and the run ends with one JSON line of totals. No fixed sleeps: each input waits
for the screen it should cause.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

from agent_phone import (
    Driver,
    Gone,
    KeyName,
    Match,
    PhoneError,
    Present,
    Q,
    Settled,
    Snapshot,
    open_phone,
)

INSTAGRAM = "com.instagram.android"
PROFILE_TAB = Q(id="profile_tab")
CREATE = Q(id="profile_header_create_button")
CAPTION = Q(id="caption_input_text_view")
NEXT = Q(id="clips_right_action_button")
THUMBNAIL = Q(id="gallery_grid_item_thumbnail")
DRAFTS = Q("Drafts", match=Match.PREFIX)
SAVE_DRAFT_DIALOG = Q("Save draft?")
KEEP_EDITING_DIALOG = Q("Keep editing your draft?")
COLD_START_MS = 30_000
SCREEN_MS = 15_000
"""Instagram takes up to 30 s to show its tabs after a cold start on the J7, and a screen inside it up
to several seconds. A bound only matters when the screen is slow: each wait returns when its
condition holds."""

Steps = list[tuple[str, float]]


def timed[T](steps: Steps, label: str, call: Callable[[], T]) -> T:
    started = time.perf_counter()
    try:
        return call()
    finally:
        steps.append((label, (time.perf_counter() - started) * 1000))
        print(f"  {label:<44} {steps[-1][1]:7.0f} ms", file=sys.stderr, flush=True)


def clip_label(path: Path) -> str:
    seconds = float(
        subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    )
    whole = round(seconds)
    return f"{whole // 60}:{whole % 60:02d}"


def open_instagram(phone: Driver) -> None:
    if phone.count(PROFILE_TAB) == 0:
        phone.launch(INSTAGRAM, wait_for=Present(PROFILE_TAB), timeout_ms=COLD_START_MS)


def to_profile(phone: Driver) -> None:
    """The profile tab, from wherever Instagram is. A reel viewer that Instagram restores after a
    cold start can cover the tabs, so back out until the tab is on screen, at most three times."""
    for _ in range(3):
        try:
            phone.click(PROFILE_TAB, wait_for=Present(CREATE), timeout_ms=SCREEN_MS)
            return
        except PhoneError:
            if phone.count(CREATE) > 0:
                return
            phone.press(KeyName.BACK, wait_for=Settled(), timeout_ms=SCREEN_MS)
    phone.click(PROFILE_TAB, wait_for=Present(CREATE), timeout_ms=SCREEN_MS)


def switch_to(phone: Driver, account: str, accounts: tuple[str, ...]) -> bool:
    """True when it switched. The handle on the profile is a button named after the account."""
    if phone.count(Q(account)) > 0:
        return False
    current = next(name for name in accounts if name != account)
    phone.click(Q(current), wait_for=Present(Q(f"{account},", match=Match.PREFIX)), timeout_ms=SCREEN_MS)
    # The row's label sums up the account's unread notifications ("account-2, 41 comments and 136
    # more"). With exactly one comment it reads "1 comment and ...", and the default policy reads
    # "comment" as a send, so the gate refuses the switch with COMMIT_REFUSED. It sends nothing, but
    # granting send here is the user's call, not this script's (FINDINGS A7-4), so the refusal
    # stops the run and says so.
    phone.click(Q(f"{account},", match=Match.PREFIX), wait_for=Present(Q(account)), timeout_ms=SCREEN_MS)
    return True


def thumbnail_of(picker: Snapshot, label: str) -> object:
    """The ref of the clip whose length label reads `label`. The label is a button that holds the
    thumbnail, and the thumbnail takes the touch, so the ref is the line just inside it."""
    for at, line in enumerate(picker.lines):
        if line.name == label and at + 1 < len(picker.lines):
            inner = picker.lines[at + 1]
            if inner.depth > line.depth and inner.ref is not None:
                return picker.ref(inner.ref)
    raise LookupError(f"no clip of length {label} in the picker")


def open_picker(phone: Driver) -> Snapshot:
    """The gallery of a new reel. Start over leaves the last session pending, clip and caption, and
    the next new reel asks "Keep editing your draft?". Its Start new video saves that session as a
    draft, as the old script does. Keep editing and the editor's X end it with no draft."""
    phone.click(Q("Create new reel"), timeout_ms=SCREEN_MS)
    for _ in range(3):
        try:
            return phone.wait(Present(THUMBNAIL), timeout_ms=4000)
        except PhoneError:
            if phone.count(KEEP_EDITING_DIALOG) == 0:
                continue
            phone.click(Q("Keep editing"), wait_for=Present(Q("Cancel")), timeout_ms=SCREEN_MS)
            phone.click(Q("Cancel"), wait_for=Present(THUMBNAIL), timeout_ms=SCREEN_MS)
    return phone.wait(Present(THUMBNAIL), timeout_ms=SCREEN_MS)


def clear_pending(phone: Driver) -> None:
    """Open a new reel and close it from the profile, so no session is left pending for the next
    run or for a person: `open_picker` ends a pending one with no draft."""
    phone.click(CREATE, wait_for=Present(Q("Create new reel")), timeout_ms=SCREEN_MS)
    open_picker(phone)
    phone.click(Q("Back to Home"), wait_for=Present(PROFILE_TAB), timeout_ms=SCREEN_MS)


def compose_and_discard(
    phone: Driver, account: str, accounts: tuple[str, ...], label: str, caption: str, steps: Steps
) -> dict:
    timed(steps, f"{account}: profile", lambda: to_profile(phone))
    switched = timed(steps, f"{account}: switch account", lambda: switch_to(phone, account, accounts))
    timed(
        steps,
        f"{account}: create new",
        lambda: phone.click(CREATE, wait_for=Present(Q("Create new reel")), timeout_ms=SCREEN_MS),
    )
    picker = timed(steps, f"{account}: new reel picker", lambda: open_picker(phone))
    assert picker is not None
    drafts = next((line.name for line in picker.lines if line.name.startswith("Drafts")), "")
    timed(
        steps,
        f"{account}: pick clip {label}",
        lambda: phone.click(thumbnail_of(picker, label), wait_for=Present(NEXT), timeout_ms=SCREEN_MS),
    )
    timed(
        steps, f"{account}: next", lambda: phone.click(NEXT, wait_for=Present(CAPTION), timeout_ms=SCREEN_MS)
    )
    timed(
        steps,
        f"{account}: caption",
        lambda: phone.set_text(CAPTION, caption, wait_for=Present(Q(value=caption)), timeout_ms=SCREEN_MS),
    )
    timed(
        steps,
        f"{account}: back to editor",
        lambda: phone.press(KeyName.BACK, wait_for=Gone(CAPTION), timeout_ms=SCREEN_MS),
    )
    timed(
        steps,
        f"{account}: back to dialog",
        lambda: phone.press(KeyName.BACK, wait_for=Present(SAVE_DRAFT_DIALOG), timeout_ms=SCREEN_MS),
    )
    after = timed(
        steps,
        f"{account}: start over",
        lambda: phone.click(Q("Start over"), wait_for=Present(DRAFTS), timeout_ms=SCREEN_MS).after,
    )
    drafts_after = next(
        (line.name for line in (after.lines if after else ()) if line.name.startswith("Drafts")), ""
    )
    timed(
        steps,
        f"{account}: close picker",
        lambda: phone.click(Q("Back to Home"), wait_for=Present(PROFILE_TAB), timeout_ms=SCREEN_MS),
    )
    timed(steps, f"{account}: clear pending session", lambda: clear_pending(phone))
    return {"account": account, "status": "dry_run", "switched": switched, "drafts": [drafts, drafts_after]}


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="publish_dry_run.py")
    parser.add_argument("serial")
    parser.add_argument("file", type=Path)
    parser.add_argument("caption")
    parser.add_argument(
        "--accounts",
        required=True,
        help="the handles of the accounts signed in on the phone, comma-separated",
    )
    parser.add_argument("--cold", action="store_true")
    parser.add_argument(
        "--clear-only", action="store_true", help="only end a pending session on each account"
    )
    args = parser.parse_args(argv)
    accounts = tuple(name.strip() for name in args.accounts.split(","))
    label = clip_label(args.file)
    steps: Steps = []
    results: list[dict] = []
    started = time.perf_counter()
    try:
        with open_phone(args.serial) as phone:
            timed(steps, "look first", phone.snapshot)
            if args.cold:
                timed(steps, "stop instagram", lambda: phone.stop(INSTAGRAM, wait_for=Settled()))
            timed(steps, "launch instagram", lambda: open_instagram(phone))
            for account in accounts:
                if args.clear_only:
                    timed(steps, f"{account}: profile", lambda: to_profile(phone))
                    timed(
                        steps, f"{account}: switch account", lambda a=account: switch_to(phone, a, accounts)
                    )
                    timed(steps, f"{account}: clear pending session", lambda: clear_pending(phone))
                    results.append({"account": account, "status": "cleared"})
                    continue
                results.append(compose_and_discard(phone, account, accounts, label, args.caption, steps))
    except (PhoneError, LookupError, AssertionError) as error:
        outcome = getattr(error, "outcome", error)
        after = getattr(outcome, "details", {}).get("after") if hasattr(outcome, "details") else None
        if after is not None:
            print(f"the last screen showed: {[line.name for line in after.lines][:12]}", file=sys.stderr)
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": str(getattr(outcome, "message", outcome)),
                    "results": results,
                    "ms": round((time.perf_counter() - started) * 1000),
                }
            )
        )
        return 3
    print(
        json.dumps(
            {
                "ok": True,
                "clip": label,
                "results": results,
                "steps": len(steps),
                "ms": round((time.perf_counter() - started) * 1000),
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
