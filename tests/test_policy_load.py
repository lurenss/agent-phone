"""What a caller's policy file can and cannot change. A consumer's file may weaken a commit, by
exempting a label or disabling a commit rule. It may never weaken a denial, and it may not widen
the languages the engine claims to read. Each case loads real files through the same functions
the CLI uses, and the CLI cases check what reached the backend."""

import shutil
import tomllib

import pytest
from fakes import J7_SERIAL, FakeHub, info_for, invoke
from support import ROOT, fixture_screen, node, screen_of

from agent_phone.cli.policy import load_policy, load_profile, load_profiles, profile_for
from agent_phone.core.device import Connected
from agent_phone.core.outcome import ErrorCode, Refusal
from agent_phone.core.policy.rules import merge, parse_policy

J7 = Connected(J7_SERIAL, "SM_J730F", ready=True)
INSTAGRAM = "com.instagram.android"
GO_LIVE = screen_of(
    node(
        "android.widget.FrameLayout",
        node(
            "android.widget.Button",
            text="Go live",
            clickable=True,
            bounds="[300,1700][780,1800]",
            package=INSTAGRAM,
        ),
        package=INSTAGRAM,
        bounds="[0,0][1080,1920]",
    )
)


def layer(path, trusted):
    doc = tomllib.loads((ROOT / path).read_text(encoding="utf-8"))
    return parse_policy(doc, path, trusted=trusted)


def install_j7(root):
    (root / "profiles").mkdir()
    (root / "instagram").mkdir()
    shutil.copy(ROOT / "examples" / "devices" / "j7.toml", root / "profiles" / "j7.toml")
    shutil.copy(ROOT / "examples" / "instagram" / "policy.toml", root / "instagram" / "policy.toml")


def caller_file(root, text):
    path = root / "caller.toml"
    path.write_text(text)
    return path


def click_go_live(root, *flags):
    code, wire = invoke(["snapshot"], FakeHub([J7], screens=[GO_LIVE]), root)
    assert code == 0, wire
    ref = next(
        t for line in wire["data"]["tree"] if "Go live" in line for t in line.split() if t.startswith("@")
    )
    hub = FakeHub([J7], screens=[GO_LIVE])
    _, wire = invoke(["click", ref, *flags], hub, root)
    return wire, [permit.action for phone in hub.phones for permit in phone.permits]


def test_the_j7_profile_denies_go_live_with_or_without_a_grant(tmp_path):
    install_j7(tmp_path)
    for flags in ([], ["--commit", "publish"]):
        wire, sent = click_go_live(tmp_path, *flags)
        assert wire["error"]["code"] == "DENIED" and wire["error"]["details"]["rule"] == "ig.no-live"
        assert sent == []


def test_a_caller_file_cannot_disable_a_deny_rule_that_the_profile_loads(tmp_path):
    install_j7(tmp_path)
    weaken = caller_file(tmp_path, 'disable = ["ig.no-live"]\n')
    wire, sent = click_go_live(tmp_path, "--policy", str(weaken), "--commit", "publish")
    assert sent == [], f"'Go live' was tapped on the J7 profile: {sent}"
    assert wire["error"]["code"] == "POLICY_INVALID" and wire["error"]["details"]["rule"] == "ig.no-live"


def test_a_second_file_of_the_profile_cannot_disable_the_first_ones_deny_rule(tmp_path):
    (tmp_path / "deny.toml").write_text('[[deny]]\nid = "p.deny"\nwords = ["x"]\nreason = "A denial."\n')
    (tmp_path / "weaken.toml").write_text('disable = ["p.deny"]\n')
    profile = tmp_path / "phone.toml"
    profile.write_text(
        f'[device]\nserial = "{J7_SERIAL}"\nname = "phone"\npolicy_files = ["deny.toml", "weaken.toml"]\n'
    )
    with pytest.raises(Refusal) as refused:
        load_policy((), load_profile(profile))
    assert refused.value.code is ErrorCode.POLICY_INVALID and refused.value.details["rule"] == "p.deny"


def test_a_caller_file_may_still_disable_a_deny_rule_that_another_caller_file_defines(tmp_path):
    (tmp_path / "deny.toml").write_text('[[deny]]\nid = "c.deny"\nwords = ["x"]\nreason = "A denial."\n')
    (tmp_path / "weaken.toml").write_text('disable = ["c.deny"]\n')
    install_j7(tmp_path)
    loaded = profile_for(load_profiles(tmp_path), J7_SERIAL)
    policy = load_policy([tmp_path / "deny.toml", tmp_path / "weaken.toml"], loaded)
    assert "c.deny" not in {rule.origin.rule for rule in policy.rules}


INSTALLER = "com.google.android.packageinstaller"
PROTECTS_A_TUNNEL = f"""
[device]
serial = "{J7_SERIAL}"
name = "test-phone"

[[protected]]
package = "com.example.tunnel"
labels = ["SafeTunnel"]
reason = "Always-on lockdown VPN."
"""


def uninstall_dialog(positive="OK"):
    """The package installer's question about SafeTunnel, with `positive` on its positive button."""
    return screen_of(
        node(
            "android.widget.FrameLayout",
            node(
                "android.widget.TextView", text="SafeTunnel", bounds="[60,1400][1020,1480]", package=INSTALLER
            ),
            node(
                "android.widget.TextView",
                text="Do you want to uninstall this app?",
                resource_id="android:id/message",
                bounds="[60,1500][1020,1600]",
                package=INSTALLER,
            ),
            node(
                "android.widget.Button",
                text="Cancel",
                resource_id="android:id/button2",
                clickable=True,
                bounds="[540,1700][780,1800]",
                package=INSTALLER,
            ),
            node(
                "android.widget.Button",
                text=positive,
                resource_id="android:id/button1",
                clickable=True,
                bounds="[780,1700][1020,1800]",
                package=INSTALLER,
            ),
            package=INSTALLER,
            bounds="[0,1350][1080,1900]",
        )
    )


UNINSTALL = uninstall_dialog()
WEAKENINGS = {
    "disable-default-delete": 'disable = ["default.delete"]\n',
    "disable-default-affirmative": 'disable = ["default.affirmative"]\n',
    "exempt-ok": '[[exempt]]\nid = "c.ok"\nlabels = ["OK"]\nreason = "OK only closes dialogs here."\n',
    "ignore-button1": (
        '[[ignore]]\nid = "c.b1"\nnode_ids = ["android:id/button1"]\nreason = "A neutral button."\n'
    ),
}


def tap_positive_of_the_uninstall_dialog(root, positive, *flags):
    screen = uninstall_dialog(positive)
    (root / "profiles").mkdir(exist_ok=True)
    (root / "profiles" / "phone.toml").write_text(PROTECTS_A_TUNNEL)
    code, wire = invoke(["snapshot"], FakeHub([J7], screens=[screen]), root)
    assert code == 0, wire
    ref = next(
        t
        for line in wire["data"]["tree"]
        if f'"{positive}"' in line
        for t in line.split()
        if t.startswith("@")
    )
    hub = FakeHub([J7], screens=[screen])
    _, wire = invoke(["click", ref, *flags], hub, root)
    return wire, [permit.action for phone in hub.phones for permit in phone.permits]


def tap_ok_of_the_uninstall_dialog(root, *flags):
    return tap_positive_of_the_uninstall_dialog(root, "OK", *flags)


def test_the_profile_alone_denies_the_ok_of_the_uninstall_dialog_of_a_protected_app(tmp_path):
    wire, sent = tap_ok_of_the_uninstall_dialog(tmp_path)
    assert wire["error"]["code"] == "DENIED"
    assert wire["error"]["details"]["rule"] == "profile.protect.com.example.tunnel.app-info"
    assert sent == []


@pytest.mark.parametrize("weakening", sorted(WEAKENINGS))
def test_no_consumer_file_turns_the_denial_of_that_ok_into_anything_else(tmp_path, weakening):
    wire, sent = tap_ok_of_the_uninstall_dialog(
        tmp_path, "--policy", str(caller_file(tmp_path, WEAKENINGS[weakening]))
    )
    assert sent == [], f"the OK of 'uninstall SafeTunnel?' was tapped: {wire.get('data', {}).get('gate')}"
    assert wire["error"]["code"] == "DENIED", wire["error"]


def a_commit(effect, word):
    return f'[[commit]]\nid = "c.mask"\neffect = "{effect}"\nwords = ["{word}"]\nreason = "A test commit."\n'


COMMITS_ON_THE_BUTTON = {
    "ok-confirms": ("confirm", a_commit("confirm", "ok")),
    "the-class-word": ("confirm", a_commit("confirm", "button")),
    "the-positive-button-id": ("confirm", a_commit("confirm", "button1")),
    "the-positive-button-id-is-social": ("social", a_commit("social", "button1")),
}
"""A consumer's commit rule that matches the OK button's own words, its class name or its
resource-id. Each gives the button an effect of its own, and the effect that the rule gives is the
grant that the refusal would ask for."""


@pytest.mark.parametrize("case", sorted(COMMITS_ON_THE_BUTTON))
def test_a_consumer_commit_rule_on_the_ok_button_does_not_lift_the_denial_of_its_dialog(tmp_path, case):
    effect, text = COMMITS_ON_THE_BUTTON[case]
    consumer = caller_file(tmp_path, text)
    for flags in ([], ["--commit", effect]):
        wire, sent = tap_ok_of_the_uninstall_dialog(tmp_path, "--policy", str(consumer), *flags)
        assert sent == [], f"the OK of 'uninstall SafeTunnel?' was tapped under {flags}: {wire}"
        assert wire["error"]["code"] == "DENIED", (
            f"no consumer rule on the button's own words removes its question's effects; got {wire['error']}"
        )
        assert wire["error"]["details"]["rule"] == "profile.protect.com.example.tunnel.app-info"


NEVER_DELETES = f"""
[device]
serial = "{J7_SERIAL}"
name = "test-phone"

[[deny]]
id = "p.never-delete"
effects = ["delete"]
reason = "Nothing is ever deleted on this phone, with or without --commit."
"""


def test_a_consumer_commit_rule_on_ok_does_not_open_a_denial_that_names_an_effect(tmp_path):
    delete_post = screen_of(
        node(
            "android.widget.FrameLayout",
            node("android.widget.TextView", text="Delete this post?", bounds="[60,1400][1020,1480]"),
            node("android.widget.Button", text="Cancel", clickable=True, bounds="[540,1700][780,1800]"),
            node("android.widget.Button", text="OK", clickable=True, bounds="[780,1700][1020,1800]"),
            bounds="[0,1350][1080,1900]",
        )
    )
    (tmp_path / "profiles").mkdir()
    (tmp_path / "profiles" / "phone.toml").write_text(NEVER_DELETES)
    consumer = caller_file(tmp_path, a_commit("confirm", "ok"))
    code, wire = invoke(["snapshot"], FakeHub([J7], screens=[delete_post]), tmp_path)
    assert code == 0, wire
    ref = next(
        t for line in wire["data"]["tree"] if '"OK"' in line for t in line.split() if t.startswith("@")
    )
    for flags in ([], ["--commit", "confirm"]):
        hub = FakeHub([J7], screens=[delete_post])
        _, wire = invoke(["click", ref, "--policy", str(consumer), *flags], hub, tmp_path)
        sent = [permit.action for phone in hub.phones for permit in phone.permits]
        assert sent == [], f"the OK of 'Delete this post?' was tapped under {flags}"
        assert wire["error"]["details"]["rule"] == "p.never-delete", wire["error"]


@pytest.mark.parametrize("positive", ["Confirm", "Submit"])
def test_a_built_in_confirm_button_under_a_denied_question_is_denied_with_no_consumer_file(
    tmp_path, positive
):
    for flags in ([], ["--commit", "confirm"]):
        wire, sent = tap_positive_of_the_uninstall_dialog(tmp_path, positive, *flags)
        assert sent == [], f"the {positive} of 'uninstall SafeTunnel?' was tapped under {flags}"
        assert wire["error"]["code"] == "DENIED", wire["error"]


NEVER_SENDS = f"""
[device]
serial = "{J7_SERIAL}"
name = "test-phone"

[[deny]]
id = "p.never-send"
effects = ["send"]
reason = "This phone never sends a message, with or without --commit."
"""


@pytest.mark.parametrize(
    ("argv", "disabled"),
    [(["press", "enter"], "default.key.enter"), (["open-url", "sms:5551234"], "default.uri.contact")],
)
def test_disabling_a_key_or_a_link_rule_does_not_switch_off_a_profile_denial(tmp_path, argv, disabled):
    settings = fixture_screen("settings-home")
    (tmp_path / "profiles").mkdir()
    (tmp_path / "profiles" / "phone.toml").write_text(NEVER_SENDS)
    assert invoke(["snapshot"], FakeHub([J7], screens=[settings]), tmp_path)[0] == 0
    _, baseline = invoke(argv, FakeHub([J7], screens=[settings]), tmp_path)
    assert baseline["error"]["code"] == "DENIED", baseline
    hub = FakeHub([J7], screens=[settings])
    consumer = caller_file(tmp_path, f'disable = ["{disabled}"]\n')
    _, wire = invoke([*argv, "--policy", str(consumer)], hub, tmp_path)
    sent = [permit.action for phone in hub.phones for permit in phone.permits]
    assert sent == [], f"{' '.join(argv)} was sent under p.never-send: {wire.get('data', {}).get('gate')}"
    assert wire["error"]["code"] == "DENIED", wire.get("error")


GERMAN = screen_of(
    node(
        "android.widget.FrameLayout",
        node("android.widget.Button", text="Löschen", clickable=True, bounds="[0,500][1080,600]"),
        package="com.android.settings",
        bounds="[0,0][1080,1920]",
    )
)


def tap_delete_on_a_german_phone(root, *flags):
    infos = {J7_SERIAL: info_for(J7_SERIAL, locale="de-DE")}
    code, wire = invoke(["snapshot"], FakeHub([J7], infos=infos, screens=[GERMAN]), root)
    assert code == 0, wire
    ref = next(
        t for line in wire["data"]["tree"] if "Löschen" in line for t in line.split() if t.startswith("@")
    )
    hub = FakeHub([J7], infos=infos, screens=[GERMAN])
    _, wire = invoke(["click", ref, *flags], hub, root)
    return wire, [permit.action for phone in hub.phones for permit in phone.permits]


def test_a_german_screen_is_not_judged_and_so_not_tapped(tmp_path):
    wire, sent = tap_delete_on_a_german_phone(tmp_path)
    assert wire["error"]["code"] == "LOCALE_UNSUPPORTED" and sent == []


def test_a_caller_file_that_only_declares_a_language_does_not_switch_the_locale_guard_off(tmp_path):
    declares = caller_file(tmp_path, 'languages = ["de"]\n')
    wire, sent = tap_delete_on_a_german_phone(tmp_path, "--policy", str(declares))
    assert sent == [], "the Löschen button was tapped with no grant, on words that no rule reads"
    assert wire["error"]["code"] == "POLICY_INVALID" and wire["error"]["details"]["field"] == "languages"
    assert str(declares) in wire["error"]["message"] and "built-in" in wire["error"]["message"]


def test_no_layer_may_declare_a_language_the_built_in_policy_does_not_cover(tmp_path):
    declares = parse_policy({"languages": ["de"]}, "extra.toml", trusted=False)
    with pytest.raises(Refusal) as refused:
        merge((layer("src/agent_phone/policy/default.toml", True), declares))
    assert refused.value.code is ErrorCode.POLICY_INVALID and "extra.toml" in refused.value.message


def test_a_file_may_name_a_covered_language_and_scope_a_rule_to_any_language(tmp_path):
    scoped = {
        "languages": ["en"],
        "commit": [
            {"id": "c.loeschen", "effect": "delete", "words": ["löschen"], "languages": ["de"], "reason": "r"}
        ],
    }
    merged = merge(
        (
            layer("src/agent_phone/policy/default.toml", True),
            parse_policy(scoped, "extra.toml", trusted=False),
        )
    )
    assert merged.languages == {"en", "it"} and "c.loeschen" in {rule.origin.rule for rule in merged.rules}
