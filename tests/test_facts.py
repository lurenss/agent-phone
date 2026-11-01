import re

import pytest
from support import ROOT

from agent_phone.adapters.uiautomator2.adb import AdbResult
from agent_phone.adapters.uiautomator2.shell import (
    FACTS_SCRIPT,
    Shell,
    facts_script,
    parse_facts,
)
from agent_phone.core.device import BootId, DeviceIdentity, Package, Serial
from agent_phone.core.geometry import Size
from agent_phone.core.outcome import ErrorCode, Refusal

SERIAL = Serial("0a1b2c3d4e5f6a7b")
RECORDED = (ROOT / "tests" / "fixtures" / "adb" / "facts-j7.txt").read_text()


def without(text: str, *fragments: str) -> str:
    return "\n".join(line for line in text.splitlines() if not any(f in line for f in fragments))


def test_the_recorded_j7_output_gives_every_fact():
    info = parse_facts(SERIAL, RECORDED)
    assert info.identity == DeviceIdentity(SERIAL, BootId("8d3f6c1e-0b5a-4c2e-9f1d-2a7b3c4d5e6f"))
    assert (info.model, info.api_level, info.abi) == ("SM-J730F", 28, "armeabi-v7a")
    assert (info.display, info.density_dpi) == (Size(1080, 1920), 420)
    assert info.locale == "en-US"
    assert info.default_ime == Package("com.sec.android.inputmethod")


def test_the_order_of_the_lines_does_not_matter():
    shuffled = "\n".join(reversed(RECORDED.splitlines()))
    assert parse_facts(SERIAL, shuffled) == parse_facts(SERIAL, RECORDED)


def test_an_override_wins_over_the_physical_size_and_density():
    info = parse_facts(SERIAL, RECORDED + "\nOverride size: 1080x1800\nOverride density: 320\n")
    assert (info.display, info.density_dpi) == (Size(1080, 1800), 320)


def test_the_locale_falls_back_to_the_product_locale_and_uses_hyphens():
    info = parse_facts(SERIAL, without(RECORDED, "persist.sys.locale") + "\n[persist.sys.locale]: []")
    assert info.locale == "en-GB"
    info = parse_facts(SERIAL, RECORDED.replace("[en-US]", "[pt_BR]"))
    assert info.locale == "pt-BR"


@pytest.mark.parametrize("keyboard", ["ime=null", "ime="])
def test_no_default_keyboard_is_none(keyboard):
    text = without(RECORDED, "ime=") + "\n" + keyboard
    assert parse_facts(SERIAL, text).default_ime is None


@pytest.mark.parametrize(
    ("dropped", "fact"),
    [
        ("ro.build.version.sdk", "API level"),
        ("ro.product.cpu.abi", "ABI"),
        ("ro.product.model", "model"),
        ("Physical size", "display size"),
        ("Physical density", "display density"),
        ("boot=", "boot id"),
        ("ime=", "default keyboard"),
    ],
)
def test_a_missing_fact_is_refused_by_name_and_never_defaulted(dropped, fact):
    with pytest.raises(Refusal) as raised:
        parse_facts(SERIAL, without(RECORDED, dropped))
    assert raised.value.code is ErrorCode.TRANSPORT
    assert fact in raised.value.message


def test_a_locale_that_no_property_gives_is_refused():
    with pytest.raises(Refusal) as raised:
        parse_facts(SERIAL, without(RECORDED, "locale"))
    assert "locale" in raised.value.message


def test_an_api_level_that_is_not_a_number_is_refused():
    with pytest.raises(Refusal) as raised:
        parse_facts(SERIAL, RECORDED.replace("[28]", "[abc]"))
    assert "API level" in raised.value.message


EMULATOR = Serial("emulator-5554")
CLEAN_EMULATOR = """boot=c1becccb-50a7-42f3-812b-85f12b78f1bc
size=Physical size: 1080x2400
density=Physical density: 420
ime=com.google.android.inputmethod.latin/com.android.inputmethod.latin.LatinIME
[persist.sys.locale]: [de-DE]
[ro.build.version.sdk]: [35]
[ro.product.cpu.abi]: [arm64-v8a]
[ro.product.locale]: [en-US]
[ro.product.model]: [sdk_gphone64_arm64]
"""
# Two of the three outputs recorded on the emulator in 300 reads; the first and the third were the same text.
GLUED_SDK_AND_IME = (
    "boot=c1becccb-50a7-42f3-812b-85f12b78f1bc\n[persist.sys.locale]: [de-DE]\n"
    "density=Physical density: 420\n[ro.build.version.sdk]: [35]"
    "ime=com.google.android.inputmethod.latin/com.android.inputmethod.latin.LatinIME\n\n"
    "size=Physical size: 1080x2400\n[ro.product.cpu.abi]: [arm64-v8a]\n"
    "[ro.product.locale]: [en-US]\n[ro.product.model]: [sdk_gphone64_arm64]"
)
GLUED_LOCALE_AND_IME = (
    "boot=c1becccb-50a7-42f3-812b-85f12b78f1bc\nsize=Physical size: 1080x2400\n"
    "[persist.sys.locale]: [de-DE]"
    "ime=com.google.android.inputmethod.latin/com.android.inputmethod.latin.LatinIME\n\n"
    "[ro.build.version.sdk]: [35]\ndensity=Physical density: 420\n"
    "[ro.product.cpu.abi]: [arm64-v8a]\n[ro.product.locale]: [en-US]\n"
    "[ro.product.model]: [sdk_gphone64_arm64]"
)
RECORDED_GLUES = [
    pytest.param(GLUED_SDK_AND_IME, id="recorded-sdk-into-ime"),
    pytest.param(GLUED_LOCALE_AND_IME, id="recorded-locale-into-ime"),
]


def glue(clean: str, prop: str, job: str) -> str:
    """The text of one property, then a whole line of another job, then the property's newline."""
    lines = [line for line in clean.splitlines() if prop not in line]
    at = next(i for i, line in enumerate(lines) if line.startswith(job))
    text = next(line for line in clean.splitlines() if prop in line)
    return "\n".join([*lines[:at], text + lines[at], "", *lines[at + 1 :]])


PROPERTIES_IN_CLEAN = [line.split("]")[0][1:] for line in CLEAN_EMULATOR.splitlines() if line.startswith("[")]
GLUES = [
    pytest.param(glue(CLEAN_EMULATOR, prop, job), id=f"{prop}-into-{job}")
    for prop in PROPERTIES_IN_CLEAN
    for job in ("boot=", "size=", "density=", "ime=")
]

garbled_read_is_accepted = pytest.mark.xfail(
    strict=True,
    reason="parse_facts skips a line it does not know, so a glued read gives a fact or a wrong one",
)


@garbled_read_is_accepted
@pytest.mark.parametrize("output", [*RECORDED_GLUES, *GLUES])
def test_a_read_with_glued_lines_is_refused_as_garbled_and_gives_no_fact(output):
    with pytest.raises(Refusal) as raised:
        parse_facts(EMULATOR, output)
    assert raised.value.code is ErrorCode.TRANSPORT
    assert raised.value.details == {"fact": "garbled"}


def test_the_clean_emulator_read_gives_its_german_locale():
    assert parse_facts(EMULATOR, CLEAN_EMULATOR).locale == "de-DE"


def test_the_wm_override_line_that_follows_its_physical_line_is_accepted():
    text = CLEAN_EMULATOR.replace(
        "size=Physical size: 1080x2400\n", "size=Physical size: 1080x2400\nOverride size: 720x1280\n"
    ).replace("density=Physical density: 420\n", "density=Physical density: 420\nOverride density: 280\n")
    info = parse_facts(EMULATOR, text)
    assert (info.display, info.density_dpi) == (Size(720, 1280), 280)


def test_a_device_with_no_persistent_locale_property_uses_the_product_locale():
    info = parse_facts(EMULATOR, without(CLEAN_EMULATOR, "persist.sys.locale"))
    assert info.locale == "en-US"


class ScriptedAdb:
    """Answers the nth `adb shell` call with the nth canned output and keeps the scripts it was sent."""

    def __init__(self, *outputs: str, status: int = 0) -> None:
        self._outputs = list(outputs)
        self._status = status
        self.scripts: list[str] = []

    def run(self, args, timeout_s=15.0):
        self.scripts.append(args[3])
        return AdbResult(self._status, self._outputs.pop(0), "adb: error: closed" if self._status else "")


TOUCH = "echo touched-the-last-use-file"
MISSING_KEYBOARD = without(CLEAN_EMULATOR, "ime=")

reads_once = pytest.mark.xfail(
    strict=True, reason="Shell.facts reads once and raises or returns whatever it parsed"
)


@reads_once
@pytest.mark.parametrize("first", [*RECORDED_GLUES, pytest.param(MISSING_KEYBOARD, id="no-ime")])
def test_a_read_that_is_refused_is_read_once_more_and_the_clean_read_wins(first):
    adb = ScriptedAdb(first, CLEAN_EMULATOR)
    info = Shell(EMULATOR, adb).facts(also=TOUCH)
    assert info == parse_facts(EMULATOR, CLEAN_EMULATOR) and info.locale == "de-DE"
    assert len(adb.scripts) == 2
    assert sum(TOUCH in script for script in adb.scripts) == 1, "the touch ran in the first read"


@reads_once
def test_a_second_garbled_read_refuses_after_exactly_two_reads():
    adb = ScriptedAdb(GLUED_SDK_AND_IME, GLUED_LOCALE_AND_IME)
    with pytest.raises(Refusal) as raised:
        Shell(EMULATOR, adb).facts()
    assert (raised.value.code, raised.value.details) == (ErrorCode.TRANSPORT, {"fact": "garbled"})
    assert len(adb.scripts) == 2


@reads_once
def test_a_second_missing_fact_refuses_by_name_after_exactly_two_reads():
    adb = ScriptedAdb(MISSING_KEYBOARD, MISSING_KEYBOARD)
    with pytest.raises(Refusal) as raised:
        Shell(EMULATOR, adb).facts()
    assert raised.value.details == {"fact": "default keyboard"}
    assert len(adb.scripts) == 2


def test_a_clean_read_is_not_read_twice():
    adb = ScriptedAdb(CLEAN_EMULATOR)
    Shell(EMULATOR, adb).facts(also=TOUCH)
    assert len(adb.scripts) == 1 and adb.scripts[0] == facts_script(TOUCH)


def test_an_adb_failure_is_not_retried_because_it_is_not_a_transient_garble():
    adb = ScriptedAdb("", status=1)
    with pytest.raises(Refusal) as raised:
        Shell(EMULATOR, adb).facts()
    assert raised.value.code is ErrorCode.TRANSPORT and len(adb.scripts) == 1


@pytest.mark.xfail(
    strict=True, reason="the property job is a pipeline, so its lines can reach the shared stdout in pieces"
)
def test_every_job_of_the_facts_script_prints_in_one_write():
    *jobs, last = FACTS_SCRIPT.split(" & ")
    assert last == "wait" and len(jobs) == 5
    assert all(re.fullmatch(r'\(echo "[a-z]*=?\$\(.*\)"\)', job) for job in jobs), jobs
