"""What a phone's adb reads say. Each parser takes the text of one read and returns a fact or
None, never a guess: a format this code does not know reads as missing, and the caller says so.

The formats are the ones in `probes/android/FINDINGS.md` (A6) and the J7's API 28 dumps. A display
is named by the `mDisplayId=` line of `dumpsys display` and read from its `mBaseDisplayInfo`, which
holds the natural size and no rotation, and a focus line sits under its `Display: mDisplayId=` header
in `dumpsys window displays`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

PROPERTY_LINE = re.compile(r"\[([^\]]+)\]: \[(.*)\]")
DISPLAY_ID = re.compile(r"^\s*mDisplayId=(\d+)\s*$")
INFO_ID = re.compile(r"\bdisplayId (\d+)")
REAL_SIZE = re.compile(r"\breal (\d+) x (\d+)")
APP_SIZE = re.compile(r"\bapp (\d+) x (\d+)")
INFO_STATE = re.compile(r", state (\w+)")
WINDOW_HEADER = re.compile(r"^\s*Display: mDisplayId=(\d+)")
WINDOW_FOCUS = re.compile(r"^\s*mCurrentFocus=(.*)$")
TOP_FOCUSED = re.compile(r"\bmTopFocusedDisplayId=(\d+)")
FOCUS_OWNER = re.compile(r"\bu\d+ ([^\s/}]+)")
WAKEFULNESS = re.compile(r"\bmWakefulness=(\w+)")
POWER_STATE = re.compile(r"Display Power: state=(\w+)")


@dataclass(frozen=True, slots=True)
class Display:
    id: int
    width: int
    height: int
    state: str | None


@dataclass(frozen=True, slots=True)
class WindowFocus:
    """`top_focused_display` is where keys go. `owners` maps a display id to the package, or the
    window name, that holds its focus. A display with no focus has no entry."""

    top_focused_display: int | None
    owners: dict[int, str]


def parse_properties(text: str) -> dict[str, str]:
    return {m[1]: m[2] for line in text.splitlines() if (m := PROPERTY_LINE.fullmatch(line.strip()))}


def parse_displays(text: str) -> list[Display]:
    """Every display `dumpsys display` describes, in the order it lists them. A base info line wins
    over any other line about the same display. A line with no size says nothing about its display."""
    found: dict[int, tuple[bool, Display]] = {}
    current: int | None = None
    for line in text.splitlines():
        if marker := DISPLAY_ID.match(line):
            current = int(marker[1])
        if "DisplayInfo{" not in line:
            continue
        named = INFO_ID.search(line)
        ident = int(named[1]) if named else current
        size = REAL_SIZE.search(line) or APP_SIZE.search(line)
        if ident is None or size is None:
            continue
        state = INFO_STATE.search(line)
        base = "mBaseDisplayInfo=" in line
        if ident not in found or (base and not found[ident][0]):
            found[ident] = (base, Display(ident, int(size[1]), int(size[2]), state[1] if state else None))
    return [display for _, display in found.values()]


def focus_owner(window: str) -> str:
    """`Window{4e4f68d u0 com.android.launcher3/com.android.launcher3.QuickstepLauncher}` names
    `com.android.launcher3`. A window with no activity, such as `StatusBar`, names itself."""
    owner = FOCUS_OWNER.search(window)
    return owner[1] if owner else window.strip()


def parse_window_displays(text: str) -> WindowFocus:
    """A dump with no `Display:` header at all is a phone with one screen, and its focus is
    display 0's. A focus line above every header of a dump that has some belongs to no display."""
    lines = text.splitlines()
    headed = any(WINDOW_HEADER.match(line) for line in lines)
    current = None if headed else 0
    top, owners = None, {}
    for line in lines:
        if header := WINDOW_HEADER.match(line):
            current = int(header[1])
        elif (focus := WINDOW_FOCUS.match(line)) and current is not None and focus[1].strip() != "null":
            owners.setdefault(current, focus_owner(focus[1]))
        elif (found := TOP_FOCUSED.search(line)) and top is None:
            top = int(found[1])
    return WindowFocus(top, owners)


def parse_top_focused(text: str) -> int | None:
    """The display that gets key input, from the first `mTopFocusedDisplayId=` line. Android 13 and 15
    print it in `dumpsys window`, not in `dumpsys window displays`, and Android 9 prints it in neither."""
    found = TOP_FOCUSED.search(text)
    return int(found[1]) if found else None


def parse_awake(text: str) -> bool | None:
    """`mWakefulness=Awake` on API 28 and later. Older dumps only have the display's power state."""
    if wake := WAKEFULNESS.search(text):
        return wake[1] == "Awake"
    if power := POWER_STATE.search(text):
        return power[1] == "ON"
    return None


def parse_setting(text: str) -> str | None:
    """`settings get` prints `null` for a key that is not set."""
    value = text.strip()
    return None if value in ("", "null") else value


def parse_flag(text: str) -> bool | None:
    return {"1": True, "0": False}.get(text.strip())
