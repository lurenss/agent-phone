import pytest
from support import ROOT

from agent_phone.adapters.uiautomator2.shell import parse_facts
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
