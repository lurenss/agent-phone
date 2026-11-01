#!/usr/bin/env python3
"""The facts of one phone, all from reads, in `<run>/facts.json`. Run it from the repo root, with a
run folder from the verify skill (`evidence.py new <feature>`):

    uv run python -I .claude/skills/port-android-device/scripts/facts.py <run> <serial>

It reads `getprop`, `dumpsys display`, `dumpsys window displays`, `dumpsys power` and two
`settings get` keys, each through `evidence.py`, and sends nothing. When `dumpsys window displays` has
no `mTopFocusedDisplayId` line it reads `dumpsys window` too. Android 15 prints the line in neither,
and then a phone with one display gets display 0, marked `top_focused_display_inferred`. It prints a
short summary and the hints: sentences that a table keyed by manufacturer, and a few facts, produce
for the person who brings the phone up.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tomllib
from dataclasses import asdict, dataclass, replace
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))

from device_calls import Recorder, Runner, run_folder  # noqa: E402
from device_reads import (  # noqa: E402
    Display,
    parse_awake,
    parse_displays,
    parse_flag,
    parse_properties,
    parse_setting,
    parse_top_focused,
)

from agent_phone.cli.policy import DEFAULT_POLICY  # noqa: E402
from agent_phone.core.policy.engine import language_of  # noqa: E402

XIAOMI = "Turn on Developer options › USB debugging (Security settings), or input is refused."
OPPO = "Turn on Developer options › Disable permission monitoring, if taps are refused."
VIVO = "Turn on Developer options › USB debugging (Security settings), if taps are refused."
MANUFACTURER_HINTS = {
    "xiaomi": XIAOMI,
    "redmi": XIAOMI,
    "poco": XIAOMI,
    "oppo": OPPO,
    "realme": OPPO,
    "oneplus": OPPO,
    "vivo": VIVO,
}
MORE_DISPLAYS = "Only display 0 is read and tapped (A6-1)."
UNKNOWN_DISPLAY = "Unknown which display gets key input."
EMULATOR = "Emulator: no live accounts. Safe for a full survey."


@dataclass(frozen=True, slots=True)
class Facts:
    """The keys of `facts.json`, in order. A fact a phone does not report is None."""

    serial: str
    manufacturer: str | None
    brand: str | None
    model: str | None
    device: str | None
    release: str | None
    api: int | None
    abi: str | None
    locale: str | None
    language: str | None
    policy_languages: tuple[str, ...]
    language_covered: bool | None
    emulator: bool
    displays: tuple[Display, ...]
    top_focused_display: int | None
    top_focused_display_inferred: bool
    awake: bool | None
    bluetooth_on: bool | None
    ime: str | None
    hints: tuple[str, ...] = ()


def policy_languages() -> tuple[str, ...]:
    return tuple(tomllib.loads(DEFAULT_POLICY.read_text(encoding="utf-8"))["languages"])


def whole(text: str | None) -> int | None:
    return int(text) if text and text.isdigit() else None


def facts_from(
    serial: str,
    getprop: str,
    display: str,
    window: str,
    power: str,
    bluetooth: str,
    ime: str,
    languages: tuple[str, ...],
    all_windows: str = "",
) -> Facts:
    """Pure: the text of each read in, the facts and their hints out. `all_windows` is `dumpsys window`,
    which names the focused display on a phone whose `dumpsys window displays` does not."""
    props = parse_properties(getprop)
    raw_locale = props.get("persist.sys.locale") or props.get("ro.product.locale")
    locale = raw_locale.replace("_", "-") if raw_locale else None
    language = language_of(locale) if locale else None
    keyboard = parse_setting(ime)
    displays = tuple(parse_displays(display))
    named = parse_top_focused(window)
    if named is None:
        named = parse_top_focused(all_windows)
    inferred = named is None and len(displays) == 1
    facts = Facts(
        serial=serial,
        manufacturer=props.get("ro.product.manufacturer") or None,
        brand=props.get("ro.product.brand") or None,
        model=props.get("ro.product.model") or None,
        device=props.get("ro.product.device") or None,
        release=props.get("ro.build.version.release") or None,
        api=whole(props.get("ro.build.version.sdk")),
        abi=props.get("ro.product.cpu.abi") or None,
        locale=locale,
        language=language,
        policy_languages=languages,
        language_covered=None if language is None else language in languages,
        emulator=serial.startswith("emulator-")
        or "1" in (props.get("ro.kernel.qemu"), props.get("ro.boot.qemu")),
        displays=displays,
        top_focused_display=0 if inferred else named,
        top_focused_display_inferred=inferred,
        awake=parse_awake(power),
        bluetooth_on=parse_flag(parse_setting(bluetooth) or ""),
        ime=keyboard.partition("/")[0] if keyboard else None,
    )
    return replace(facts, hints=hints_for(facts))


def hints_for(facts: Facts) -> tuple[str, ...]:
    found = [MANUFACTURER_HINTS.get((name or "").casefold()) for name in (facts.manufacturer, facts.brand)]
    hints = [hint for at, hint in enumerate(found) if hint and hint not in found[:at]]
    if len(facts.displays) > 1:
        hints.append(MORE_DISPLAYS)
    if facts.top_focused_display not in (None, 0):
        hints.append(
            f"Keys go to display {facts.top_focused_display}, not display 0 (A6-1). "
            "press back and press home may miss the screen that agent-phone reads."
        )
    if facts.top_focused_display is None and len(facts.displays) > 1:
        hints.append(UNKNOWN_DISPLAY)
    if facts.language_covered is False:
        hints.append(
            f"The policy has no rules for {facts.language}. "
            "Every labeled input is refused until its words are added."
        )
    if facts.emulator:
        hints.append(EMULATOR)
    return tuple(hints)


def keys_line(facts: Facts) -> str:
    if facts.top_focused_display is None:
        return "keys go to an unknown display"
    inferred = " (inferred)" if facts.top_focused_display_inferred else ""
    return f"keys go to display {facts.top_focused_display}{inferred}"


def summary(facts: Facts) -> list[str]:
    shown = ", ".join(f"{d.id}: {d.width}x{d.height} {d.state or '?'}" for d in facts.displays)
    wake = {True: "awake", False: "asleep", None: "wake state unknown"}[facts.awake]
    bluetooth = {True: "on", False: "off", None: "unknown"}[facts.bluetooth_on]
    covered = {True: "covered", False: "NOT covered", None: "unknown"}[facts.language_covered]
    lines = [
        f"serial {facts.serial}{' (emulator)' if facts.emulator else ''}",
        f"{facts.manufacturer} {facts.model} ({facts.device}), {facts.abi}",
        f"Android {facts.release} (API {facts.api})",
        f"locale {facts.locale}, language {facts.language} {covered} ({', '.join(facts.policy_languages)})",
        f"displays {shown or 'none read'}; {keys_line(facts)}",
        f"{wake}, bluetooth {bluetooth}, keyboard {facts.ime}",
    ]
    return lines + [f"hint: {hint}" for hint in facts.hints]


def read_facts(recorder: Recorder) -> Facts | None:
    """None when the phone gave no properties: it is not ready, or adb cannot reach it."""
    getprop = recorder.adb("facts-getprop", "shell", "getprop")
    if getprop.record["exit"] != 0 or not parse_properties(getprop.text):
        return None
    texts = {
        label: recorder.adb(f"facts-{label}", "shell", *command.split()).text
        for label, command in (
            ("display", "dumpsys display"),
            ("window", "dumpsys window displays"),
            ("power", "dumpsys power"),
            ("bluetooth", "settings get global bluetooth_on"),
            ("ime", "settings get secure default_input_method"),
        )
    }
    named = parse_top_focused(texts["window"]) is not None
    all_windows = "" if named else recorder.adb("facts-window-all", "shell", "dumpsys", "window").text
    return facts_from(
        recorder.serial,
        getprop.text,
        texts["display"],
        texts["window"],
        texts["power"],
        texts["bluetooth"],
        texts["ime"],
        policy_languages(),
        all_windows,
    )


def main(argv: list[str], runner: Runner = subprocess.run) -> int:
    parser = argparse.ArgumentParser(
        prog="facts.py", description="Read a phone's facts into <run>/facts.json."
    )
    parser.add_argument("run", type=run_folder)
    parser.add_argument("serial")
    args = parser.parse_args(argv)
    facts = read_facts(Recorder(args.run, args.serial, runner))
    if facts is None:
        print(
            f"facts: adb returned no properties for {args.serial}. Is it connected and authorized?",
            file=sys.stderr,
        )
        return 1
    document = json.dumps(asdict(facts), indent=1, ensure_ascii=False) + "\n"
    (args.run / "facts.json").write_text(document, encoding="utf-8")
    print("\n".join(summary(facts)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
