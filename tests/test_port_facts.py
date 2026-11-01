"""facts.py turns the text of six adb reads into `facts.json`. The canned outputs below follow the
J7's API 28 conventions and the AYN Thor's Android 13 dumps (A6), and each missing case is a phone
whose output does not say what the parser looks for."""

import json

import pytest
from port_support import FakePhone, Screen, script, shared
from support import ROOT

ADB = ROOT / "tests" / "fixtures" / "adb"
facts = script("facts")
reads = shared("device_reads")

J7_PROPS = """[persist.sys.locale]: [en-US]
[ro.build.version.release]: [9]
[ro.build.version.sdk]: [28]
[ro.product.brand]: [samsung]
[ro.product.cpu.abi]: [armeabi-v7a]
[ro.product.device]: [j7y17lte]
[ro.product.locale]: [en-GB]
[ro.product.manufacturer]: [samsung]
[ro.product.model]: [SM-J730F]
"""
J7_DISPLAY = (ADB / "dumpsys-display-j7.txt").read_text()
J7_WINDOW = """WINDOW MANAGER DISPLAY CONTENTS (dumpsys window displays)
  Display: mDisplayId=0
    init=1080x1920 420dpi cur=1080x1920 app=1080x1794
  mCurrentFocus=Window{4e4f68d u0 com.sec.android.app.launcher/.Launcher}
"""
THOR_PROPS = (
    J7_PROPS.replace("[en-US]", "[it_VA]")
    .replace("samsung", "AYN")
    .replace("SM-J730F", "Thor")
    .replace("j7y17lte", "kalama")
    .replace("[28]", "[33]")
    .replace("[9]", "[13]")
    .replace("armeabi-v7a", "arm64-v8a")
)
THOR_DISPLAY = (ADB / "dumpsys-display-thor.txt").read_text()
THOR_WINDOW = """WINDOW MANAGER DISPLAY CONTENTS (dumpsys window displays)
  Display: mDisplayId=4 (organized)
    init=1080x1240 369dpi
  mCurrentFocus=Window{310cce3 u0 primaryScreenTopLayout}
  Display: mDisplayId=0 (organized)
    init=1080x1920 369dpi
  mCurrentFocus=Window{4e4f68d u0 com.android.launcher3/com.android.launcher3.uioverrides.QuickstepLauncher}
  mTopFocusedDisplayId=0
"""
AWAKE = "Power Manager State:\n  mWakefulness=Awake\n"
KEYBOARD = "com.sec.android.inputmethod/.SamsungKeypad\n"
LANGUAGES = ("en", "it")


def facts_of(serial="S1", props=J7_PROPS, display="", window="", power="", bluetooth="", ime=""):
    return facts.facts_from(serial, props, display, window, power, bluetooth, ime, LANGUAGES)


def test_the_j7_reads_give_every_fact_and_no_hint():
    got = facts_of("0a1b2c3d4e5f6a7b", J7_PROPS, J7_DISPLAY, J7_WINDOW, AWAKE, "0\n", KEYBOARD)
    assert (got.manufacturer, got.brand, got.model, got.device) == (
        "samsung",
        "samsung",
        "SM-J730F",
        "j7y17lte",
    )
    assert (got.release, got.api, got.abi) == ("9", 28, "armeabi-v7a")
    assert (got.locale, got.language, got.language_covered) == ("en-US", "en", True)
    assert got.policy_languages == LANGUAGES and got.emulator is False
    assert got.displays == (reads.Display(0, 1080, 1920, "ON"),)
    assert got.top_focused_display is None, "API 28 prints no mTopFocusedDisplayId"
    assert (got.awake, got.bluetooth_on, got.ime) == (True, False, "com.sec.android.inputmethod")
    assert got.hints == ()


def test_the_thor_has_two_displays_with_their_states_and_keys_go_to_display_0():
    got = facts_of(
        "8c9d0e1f",
        THOR_PROPS,
        THOR_DISPLAY,
        THOR_WINDOW,
        AWAKE,
        "1\n",
        "com.google.android.inputmethod.latin/.LatinIME",
    )
    assert got.displays == (reads.Display(0, 1080, 1920, "ON"), reads.Display(4, 1080, 1240, "OFF"))
    assert (got.locale, got.language, got.language_covered) == ("it-VA", "it", True)
    assert got.top_focused_display == 0 and got.bluetooth_on is True
    assert got.hints == ("Only display 0 is read and tapped (A6-1).",)


def test_the_base_display_info_wins_over_the_override_and_the_override_alone_still_gives_a_size():
    assert reads.parse_displays(J7_DISPLAY) == [reads.Display(0, 1080, 1920, "ON")]
    only_override = "\n".join(line for line in J7_DISPLAY.splitlines() if "mBaseDisplayInfo" not in line)
    assert reads.parse_displays(only_override) == [reads.Display(0, 1080, 1920, "ON")]
    reordered = "\n".join(sorted(J7_DISPLAY.splitlines(), key=lambda line: "mBase" not in line))
    assert reads.parse_displays(reordered)[0].width == 1080


def test_a_display_text_with_no_size_gives_no_display():
    assert reads.parse_displays("") == []
    assert reads.parse_displays("Logical Displays: size=1\n  Display 0:\n    mDisplayId=0\n") == []
    assert reads.parse_displays('mBaseDisplayInfo=DisplayInfo{"x", rotation 0}') == []


@pytest.mark.parametrize(
    ("manufacturer", "brand", "hint"),
    [
        (
            "Xiaomi",
            "Redmi",
            "Turn on Developer options › USB debugging (Security settings), or input is refused.",
        ),
        (
            "Xiaomi",
            "POCO",
            "Turn on Developer options › USB debugging (Security settings), or input is refused.",
        ),
        ("OPPO", "realme", "Turn on Developer options › Disable permission monitoring, if taps are refused."),
        (
            "OnePlus",
            "OnePlus",
            "Turn on Developer options › Disable permission monitoring, if taps are refused.",
        ),
        (
            "vivo",
            "vivo",
            "Turn on Developer options › USB debugging (Security settings), if taps are refused.",
        ),
    ],
)
def test_a_manufacturer_gets_its_own_developer_options_hint_once(manufacturer, brand, hint):
    props = J7_PROPS.replace("[samsung]", "[SAMSUNG]", 1)
    props = props.replace("[SAMSUNG]", f"[{brand}]").replace(
        "[ro.product.manufacturer]: [samsung]", f"[ro.product.manufacturer]: [{manufacturer}]"
    )
    assert facts_of(props=props).hints == (hint,)


def test_a_language_the_policy_does_not_cover_says_so_and_a_covered_one_does_not():
    props = J7_PROPS.replace("[en-US]", "[ar_EG]")
    got = facts_of(props=props)
    assert (got.locale, got.language, got.language_covered) == ("ar-EG", "ar", False)
    assert got.hints == (
        "The policy has no rules for ar. Every labeled input is refused until its words are added.",
    )
    assert facts_of(props=J7_PROPS.replace("[en-US]", "[IT-it]")).language_covered is True


@pytest.mark.parametrize("prop", ["ro.kernel.qemu", "ro.boot.qemu"])
def test_an_emulator_property_marks_an_emulator_and_says_it_is_safe(prop):
    got = facts_of(props=J7_PROPS + f"[{prop}]: [1]\n")
    assert got.emulator is True
    assert got.hints == ("Emulator: no live accounts. Safe for a full survey.",)
    assert facts_of(props=J7_PROPS + f"[{prop}]: [0]\n").emulator is False


def test_an_emulator_serial_marks_an_emulator_without_the_property():
    assert facts_of("emulator-5554").emulator is True


def test_keys_that_go_to_another_display_are_a_hint():
    window = THOR_WINDOW.replace("mTopFocusedDisplayId=0", "mTopFocusedDisplayId=4")
    got = facts_of(window=window)
    assert got.top_focused_display == 4
    assert len(got.hints) == 1 and got.hints[0].startswith("Keys go to display 4, not display 0")


def test_reads_that_say_nothing_give_missing_facts_and_no_hint():
    got = facts_of(props="")
    assert (got.manufacturer, got.model, got.api, got.abi, got.locale, got.language) == (None,) * 6
    assert got.language_covered is None and got.emulator is False
    assert (got.displays, got.top_focused_display, got.awake, got.bluetooth_on, got.ime) == (
        (),
        None,
        None,
        None,
        None,
    )
    assert got.hints == ()


def test_the_product_locale_stands_in_for_an_unset_system_locale():
    props = J7_PROPS.replace("[persist.sys.locale]: [en-US]", "[persist.sys.locale]: []")
    assert facts_of(props=props).locale == "en-GB"


@pytest.mark.parametrize(
    ("text", "awake"),
    [
        ("mWakefulness=Awake", True),
        ("mWakefulness=Asleep", False),
        ("mWakefulness=Dozing", False),
        ("Display Power: state=ON", True),
        ("Display Power: state=OFF", False),
        ("nothing here", None),
        ("", None),
    ],
)
def test_the_power_dump_says_awake_asleep_or_nothing(text, awake):
    assert reads.parse_awake(text) is awake


@pytest.mark.parametrize(
    ("text", "flag"), [("1\n", True), ("0\n", False), ("null\n", None), ("", None), ("2", None)]
)
def test_a_settings_flag_is_on_off_or_unknown(text, flag):
    assert reads.parse_flag(text) is flag


def test_a_focus_line_belongs_to_the_display_header_above_it():
    focus = reads.parse_window_displays(THOR_WINDOW)
    assert focus.owners == {4: "primaryScreenTopLayout", 0: "com.android.launcher3"}
    assert focus.top_focused_display == 0


def test_a_window_dump_with_no_display_header_is_one_screen_and_a_null_focus_is_none():
    single = "mCurrentFocus=Window{1 u0 com.android.settings/com.android.settings.Settings}\n"
    assert reads.parse_window_displays(single).owners == {0: "com.android.settings"}
    assert reads.parse_window_displays("  Display: mDisplayId=0\n  mCurrentFocus=null\n").owners == {}
    above = "  mCurrentFocus=Window{1 u0 a.b/.C}\n  Display: mDisplayId=0\n"
    assert reads.parse_window_displays(above).owners == {}
    assert reads.parse_window_displays("") == reads.WindowFocus(None, {})


def test_a_focus_names_its_package_or_its_window():
    assert reads.focus_owner("Window{4e4f68d u0 com.a.b/com.a.b.Main}") == "com.a.b"
    assert reads.focus_owner("Window{4e4f68d u10 com.a.b/.Main EXITING}") == "com.a.b"
    assert reads.focus_owner("Window{4e4f68d u0 StatusBar}") == "StatusBar"


def phone() -> FakePhone:
    return FakePhone(
        serial="S1",
        screens={"home": Screen("com.android.launcher3")},
        screen="home",
        shell={
            "dumpsys display": THOR_DISPLAY,
            "dumpsys window displays": THOR_WINDOW,
            "dumpsys power": AWAKE,
            "settings get global bluetooth_on": "0\n",
            "settings get secure default_input_method": KEYBOARD,
        },
    )


def test_the_script_reads_through_evidence_and_writes_the_facts(tmp_path, capsys):
    fake = phone()
    fake.shell["getprop"] = THOR_PROPS
    assert facts.main([str(tmp_path), "S1"], fake.runner) == 0
    document = json.loads((tmp_path / "facts.json").read_text())
    assert list(document) == [
        "serial", "manufacturer", "brand", "model", "device", "release", "api", "abi", "locale",
        "language", "policy_languages", "language_covered", "emulator", "displays",
        "top_focused_display", "awake", "bluetooth_on", "ime", "hints",
    ]  # fmt: skip
    assert document["displays"][1] == {"id": 4, "width": 1080, "height": 1240, "state": "OFF"}
    assert document["policy_languages"] == ["en", "it"] and document["language_covered"] is True
    assert document["hints"] == ["Only display 0 is read and tapped (A6-1)."]
    records = sorted(path.stem for path in tmp_path.glob("facts-*.json"))
    assert records == [
        "facts-bluetooth",
        "facts-display",
        "facts-getprop",
        "facts-ime",
        "facts-power",
        "facts-window",
    ]
    assert all(not json.loads((tmp_path / f"{name}.json").read_text())["input"] for name in records)
    assert "hint: Only display 0 is read and tapped (A6-1)." in capsys.readouterr().out


def test_the_policy_languages_are_the_ones_in_the_default_policy():
    assert facts.policy_languages() == ("en", "it")


def test_a_phone_that_returns_no_properties_writes_no_facts_and_exits_1(tmp_path, capsys):
    assert facts.main([str(tmp_path), "S1"], phone().runner) == 1
    assert not (tmp_path / "facts.json").exists()
    assert "no properties" in capsys.readouterr().err
