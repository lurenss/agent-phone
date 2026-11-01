"""Input commands as an agent runs them: one process per command, refs on disk, profiles and policy
files from the state root. The fake hub keeps every phone it opened, so each test can say what
reached a device and what never did."""

import os
import shutil

import pytest
from fakes import EMULATOR_SERIAL, J7_SERIAL, FakeHub, FakePhone, info_for, invoke
from support import ROOT, fixture_screen, node, screen_of

from agent_phone.cli.policy import load_policy, load_profiles
from agent_phone.core.device import BootId, Connected
from agent_phone.core.outcome import ErrorCode, Refusal
from agent_phone.core.phone import Stop, Tap
from agent_phone.core.policy.rules import DenyRule

J7 = Connected(J7_SERIAL, "SM_J730F", ready=True)
EMULATOR = Connected(EMULATOR_SERIAL, "emu", ready=True)
SETTINGS = fixture_screen("settings-home")
BRIGHTNESS = screen_of(
    node(
        "android.widget.FrameLayout",
        node("android.widget.TextView", text="Brightness", bounds="[0,200][1080,300]"),
        package="com.android.settings",
        bounds="[0,0][1080,1920]",
    )
)


def snapshot(root, hub=None):
    code, wire = invoke(["snapshot"], hub or FakeHub([J7], screens=[SETTINGS]), root)
    assert code == 0
    return wire["data"]["id"]


def sent(hub):
    return [permit.action for phone in hub.phones for permit in phone.permits]


def profile(root, text):
    (root / "profiles").mkdir(exist_ok=True)
    (root / "profiles" / "phone.toml").write_text(text)


PROTECTS_SETTINGS = f"""
[device]
serial = "{J7_SERIAL}"
name = "test-phone"

[[protected]]
package = "com.android.settings"
labels = ["Settings"]
reason = "A test protection."
"""


def test_a_ref_taken_before_an_input_is_stale_and_its_retry_sends_nothing(tmp_path):
    taken = snapshot(tmp_path)
    hub = FakeHub([J7], screens=[SETTINGS], after_input=[BRIGHTNESS])
    code, wire = invoke(["click", f"@{taken}:e7"], hub, tmp_path)
    assert code == 0 and (wire["delivery"], wire["retry"]) == ("delivered_unverified", "unsafe")
    assert wire["data"]["input"]["kind"] == "tap" and wire["data"]["target"]["name"] == "Display"
    retry = FakeHub([J7], screens=[SETTINGS])
    code, wire = invoke(["click", f"@{taken}:e7"], retry, tmp_path)
    assert (
        code == 1 and wire["error"]["code"] == "STALE_REF" and wire["error"]["details"] == {"reason": "spent"}
    )
    assert (wire["delivery"], wire["retry"]) == ("not_delivered", "safe")
    assert sent(retry) == [] and retry.phones[0].reads == 0


def test_a_wait_for_proves_the_tap_and_returns_the_next_screen_with_fresh_refs(tmp_path):
    taken = snapshot(tmp_path)
    hub = FakeHub([J7], screens=[SETTINGS], after_input=[BRIGHTNESS])
    code, wire = invoke(["click", f"@{taken}:e7", "--wait-for", "name=Brightness"], hub, tmp_path)
    assert code == 0 and wire["delivery"] == "delivered_verified"
    assert wire["data"]["verified_by"] == 'present name="Brightness"'
    assert wire["data"]["after"]["tree"] == ['text "Brightness" [0,200,1080,300]']


def test_a_ref_used_with_another_devices_serial_never_opens_that_device(tmp_path):
    taken = snapshot(tmp_path)
    hub = FakeHub([J7, EMULATOR], screens=[SETTINGS])
    code, wire = invoke(["-d", EMULATOR_SERIAL, "click", f"@{taken}:e7"], hub, tmp_path)
    assert code == 1 and wire["error"]["code"] == "WRONG_DEVICE" and wire["delivery"] == "not_delivered"
    assert hub.phones == []


def test_a_ref_from_before_a_recorded_reboot_is_refused_before_the_screen_is_read(tmp_path):
    taken = snapshot(tmp_path)
    rebooted = FakeHub(
        [J7], infos={J7_SERIAL: info_for(J7_SERIAL, boot=BootId("a-later-boot"))}, screens=[SETTINGS]
    )
    code, wire = invoke(["click", f"@{taken}:e7"], rebooted, tmp_path)
    assert (
        code == 1
        and wire["error"]["code"] == "STALE_REF"
        and wire["error"]["details"] == {"reason": "rebooted"}
    )
    assert rebooted.phones[0].reads == 0 and sent(rebooted) == []


def test_a_policy_file_makes_a_tile_a_commit_and_the_tap_is_refused(tmp_path):
    rule = tmp_path / "display.toml"
    rule.write_text(
        '[[commit]]\nid = "t.display"\neffect = "confirm"\nwords = ["display"]\n'
        'packages = ["com.android.settings"]\nreason = "A test commit."\n'
    )
    taken = snapshot(tmp_path)
    hub = FakeHub([J7], screens=[SETTINGS])
    code, wire = invoke(["click", f"@{taken}:e7", "--policy", str(rule)], hub, tmp_path)
    assert code == 1 and wire["error"]["code"] == "COMMIT_REFUSED"
    assert wire["error"]["details"]["effects"] == ["confirm"] and wire["retry"] == "safe"
    assert sent(hub) == []
    code, wire = invoke(["click", f"@{taken}:e7"], FakeHub([J7], screens=[SETTINGS]), tmp_path)
    assert code == 0, "the rule applies only to the call that names its file"


def test_the_device_profile_protects_a_package_and_devices_names_the_profile(tmp_path):
    profile(tmp_path, PROTECTS_SETTINGS)
    snapshot(tmp_path)
    hub = FakeHub([J7], screens=[SETTINGS])
    code, wire = invoke(["stop", "com.android.settings"], hub, tmp_path)
    assert code == 1 and wire["error"]["code"] == "DENIED" and wire["delivery"] == "not_delivered"
    assert wire["error"]["details"]["rule"] == "profile.protect.com.android.settings.stop"
    assert sent(hub) == []
    code, wire = invoke(["devices"], FakeHub([J7]), tmp_path)
    assert wire["data"]["devices"][0]["profile"] == "test-phone"
    other = FakeHub([J7], screens=[SETTINGS])
    os.remove(tmp_path / "profiles" / "phone.toml")
    snapshot(tmp_path)
    code, _ = invoke(["stop", "com.android.settings"], other, tmp_path)
    assert code == 0 and sent(other) == [Stop("com.android.settings")]


def test_a_profile_that_does_not_parse_stops_every_command_before_the_device_is_opened(tmp_path):
    profile(tmp_path, "[device]\nserial = 7\n")
    for argv in (["press", "back"], ["devices"]):
        hub = FakeHub([J7], screens=[SETTINGS])
        code, wire = invoke(argv, hub, tmp_path)
        assert code == 1 and wire["error"]["code"] == "POLICY_INVALID" and hub.phones == []


def test_the_j7_profile_and_the_policy_file_it_names_load_from_the_state_root(tmp_path):
    (tmp_path / "profiles").mkdir()
    shutil.copy(ROOT / "examples" / "devices" / "j7.toml", tmp_path / "profiles" / "j7.toml")
    (tmp_path / "instagram").mkdir()
    shutil.copy(ROOT / "examples" / "instagram" / "policy.toml", tmp_path / "instagram" / "policy.toml")
    [loaded] = load_profiles(tmp_path)
    assert loaded.profile.serial == J7_SERIAL and [p.package for p in loaded.profile.protected] == [
        "hev.sockstun"
    ]
    policy = load_policy((), loaded)
    denies = {rule.origin.rule: rule.from_profile for rule in policy.of_kind(DenyRule)}
    assert denies == {
        "profile.protect.hev.sockstun.stop": True,
        "profile.protect.hev.sockstun.app-info": True,
        "j7.vpn-lockdown": True,
        "ig.no-live": False,
    }


def test_an_exception_after_a_spend_is_reported_as_delivery_uncertain(tmp_path):
    class Breaks(FakePhone):
        def inject(self, permit):
            super().inject(permit)
            raise RuntimeError("the backend fell over mid-input")

    class Hub(FakeHub):
        def open(self, serial, first_read=False):
            phone = Breaks(info_for(serial), SETTINGS)
            self.phones.append(phone)
            return phone

    taken = snapshot(tmp_path)
    hub = Hub([J7])
    code, wire = invoke(["click", f"@{taken}:e7"], hub, tmp_path)
    assert code == 1 and wire["error"]["code"] == "INTERNAL"
    assert (wire["delivery"], wire["retry"]) == ("delivery_uncertain", "unsafe")
    assert [type(action) for action in sent(hub)] == [Tap]


def test_a_screenshot_is_a_private_file_under_the_state_root_and_the_clipboard_is_read(tmp_path):
    code, wire = invoke(["screenshot"], FakeHub([J7], screens=[SETTINGS]), tmp_path)
    path = wire["data"]["value"]
    assert code == 0 and path.startswith(str(tmp_path / "devices" / J7_SERIAL / "screenshots"))
    assert oct(os.stat(path).st_mode & 0o777) == "0o600"
    code, wire = invoke(["clipboard", "get"], FakeHub([J7], screens=[SETTINGS]), tmp_path)
    assert code == 0 and wire["command"] == "clipboard get" and wire["data"] == {"value": ""}


def test_a_set_text_that_reads_back_its_text_is_verified(tmp_path):
    def search(text=""):
        return screen_of(
            node(
                "android.widget.FrameLayout",
                node(
                    "android.widget.EditText",
                    text=text,
                    hint="Search",
                    clickable=True,
                    bounds="[0,100][1080,200]",
                ),
                package="com.android.settings",
                bounds="[0,0][1080,1920]",
            )
        )

    taken = snapshot(tmp_path, FakeHub([J7], screens=[search()]))
    hub = FakeHub([J7], screens=[search()], after_input=[search("display")])
    code, wire = invoke(["set-text", f"@{taken}:e1", "display"], hub, tmp_path)
    assert code == 0 and wire["delivery"] == "delivered_verified"
    assert wire["data"]["input"] == {"kind": "set_text", "secret": False}
    assert "display" not in str(wire["data"]["input"])


def test_malformed_input_arguments_are_refused_before_any_device_is_chosen(tmp_path):
    for argv in (
        ["stop", "not a package"],
        ["launch", "com.android.settings;reboot"],
        ["click", "e7"],
        ["click", "@k3x9q:e7", "--wait-for", "Display"],
        ["scroll", "sideways"],
        ["press", "power"],
    ):
        hub = FakeHub([J7], screens=[SETTINGS])
        code, wire = invoke(argv, hub, tmp_path)
        assert code == 2 and wire["error"]["code"] == "INVALID_ARGS" and hub.phones == [], argv


def test_an_intent_with_anything_but_an_action_and_a_package_is_refused_before_it_is_judged(tmp_path):
    snapshot(tmp_path)
    hub = FakeHub([J7], screens=[SETTINGS])
    uri = "intent:#Intent;action=android.intent.action.CALL;component=x/y;end"
    code, wire = invoke(["open-url", uri], hub, tmp_path)
    assert code == 2 and wire["error"]["code"] == "INVALID_ARGS" and sent(hub) == []


@pytest.mark.xfail(strict=True, reason="a refusal after the input went out is printed as not_delivered")
def test_a_failure_after_an_input_went_out_is_never_reported_as_not_delivered(tmp_path):
    class ClosesBadly(FakePhone):
        def close(self):
            raise Refusal(ErrorCode.TRANSPORT, "the forward would not close")

    class Hub(FakeHub):
        def open(self, serial, first_read=False):
            phone = ClosesBadly(info_for(serial), SETTINGS)
            self.phones.append(phone)
            return phone

    taken = snapshot(tmp_path)
    code, wire = invoke(["click", f"@{taken}:e7"], Hub([J7]), tmp_path)
    assert code == 1 and wire["delivery"] != "not_delivered" and wire["retry"] == "unsafe"
