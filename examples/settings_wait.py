"""Open a known Settings page and read it with no sleeps, through agent_phone's public API only
(the check of plan unit 5).

Each step sends one input, and `Driver.wait` then reads the screen until the condition that input
should cause holds. The next step starts the moment it does. A fixed sleep picks one delay for
every phone, so it is too long when the phone is fast and too short when it is slow. It also gives
the next input no observation, and `wait` records one.

Run it from the repo root with the phone on its home screen, whose app it takes from the first
snapshot and waits for again at the end:

    uv run python examples/settings_wait.py [SERIAL]

It sends `launch com.android.settings`, one Settings intent, back and home. It never taps, types
or scrolls, and it prints how long each step took.
"""

from __future__ import annotations

import sys
import time
from collections.abc import Callable

from agent_phone import (
    Driver,
    Foreground,
    Gone,
    KeyName,
    Package,
    PhoneError,
    Present,
    Q,
    Role,
    Snapshot,
    open_phone,
)

SETTINGS = Package("com.android.settings")
DISPLAY_PAGE = "intent:#Intent;action=android.settings.DISPLAY_SETTINGS;end"
BRIGHTNESS = Q("Brightness")

Steps = list[tuple[str, float]]


def timed[T](steps: Steps, label: str, call: Callable[[], T]) -> T:
    started = time.perf_counter()
    try:
        return call()
    finally:
        steps.append((label, (time.perf_counter() - started) * 1000))


def read_brightness(phone: Driver, page: Snapshot) -> str:
    """The Brightness row holds a slider. Read its value live, with a ref from the page that
    `wait` recorded: no snapshot is taken between the wait and the read."""
    for at, row in enumerate(page.lines):
        if row.name != "Brightness":
            continue
        for line in page.lines[at + 1 :]:
            if line.depth <= row.depth:
                break
            if line.role is Role.SLIDER and line.ref is not None:
                value = phone.get(page.ref(line.ref))
                return value if isinstance(value, str) else ""
        return row.detail
    raise LookupError("the Display page shows no Brightness row")


def read_display_page(phone: Driver, steps: Steps) -> str:
    home = timed(steps, "look first", phone.snapshot).package

    timed(steps, "launch settings", lambda: phone.launch(SETTINGS))
    timed(steps, "wait: settings in the foreground", lambda: phone.wait(Foreground(SETTINGS)))

    timed(steps, "open the display page", lambda: phone.open_uri(DISPLAY_PAGE))
    page = timed(steps, "wait: brightness row", lambda: phone.wait(Present(BRIGHTNESS)))

    brightness = timed(steps, "read the brightness slider", lambda: read_brightness(phone, page))

    timed(steps, "press back", lambda: phone.press(KeyName.BACK))
    timed(steps, "wait: display page gone", lambda: phone.wait(Gone(BRIGHTNESS)))

    timed(steps, "press home", lambda: phone.press(KeyName.HOME))
    timed(steps, "wait: home screen back", lambda: phone.wait(Foreground(home)))
    return brightness


def report(steps: Steps, brightness: str) -> None:
    print(f"brightness slider value: {brightness}")
    width = max(len(label) for label, _ in steps)
    for label, ms in steps:
        print(f"{label:<{width}}  {ms:7.0f} ms")
    print(f"{'total':<{width}}  {sum(ms for _, ms in steps):7.0f} ms")


def main(argv: list[str]) -> int:
    steps: Steps = []
    try:
        with open_phone(argv[0] if argv else None) as phone:
            brightness = read_display_page(phone, steps)
    except PhoneError as error:
        outcome = error.outcome
        print(f"stopped: {getattr(outcome, 'message', outcome)}", file=sys.stderr)
        after = getattr(outcome, "details", {}).get("after")
        if after is not None:
            print(f"the last screen showed: {[line.name for line in after.lines]}", file=sys.stderr)
        report(steps, "not read")
        return 1
    report(steps, brightness)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
