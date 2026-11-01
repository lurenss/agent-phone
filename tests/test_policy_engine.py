"""The policy engine on real screens and on the rules that ship: what an input commits, what
no grant opens, and what a device profile protects."""

import tomllib

import pytest
from support import ROOT, consumer_of, fixture_screen, labelled, node, screen_of

from agent_phone.core.act.hit import context_labels, plan_point
from agent_phone.core.device import DeviceProfile, Package, ProtectedPackage, Serial
from agent_phone.core.labels import surface_of
from agent_phone.core.outcome import ErrorCode, Refusal
from agent_phone.core.phone import Key, KeyName, Launch, NodeAddress, OpenUri, Stop, Tap
from agent_phone.core.policy.engine import (
    Clear,
    ClearReason,
    Commits,
    Denied,
    Grant,
    Site,
    Source,
    classify,
    require,
)
from agent_phone.core.policy.rules import Effect, Policy, merge, parse_policy, protect_rules
from agent_phone.core.screen import Node, Screen, WindowKind


def layer(path, from_profile=False):
    doc = tomllib.loads((ROOT / path).read_text(encoding="utf-8"))
    if from_profile:
        doc = {key: value for key, value in doc.items() if key not in ("device", "protected")}
    return parse_policy(doc, path, from_profile)


DEFAULT = layer("src/agent_phone/policy/default.toml")
POLICY = merge((DEFAULT,))
J7 = DeviceProfile(
    Serial("0a1b2c3d4e5f6a7b"),
    "j7",
    (ProtectedPackage(Package("hev.sockstun"), ("SocksTun",), "Always-on lockdown VPN."),),
    (),
)
PROFILE = (
    Policy(frozenset(), protect_rules(J7, "j7.toml") + layer("examples/devices/j7.toml", True)[0].rules),
    frozenset(),
)


def tap_on(screen: Screen, target: Node, policy: Policy = POLICY, locale: str = "en-US"):
    point = plan_point(screen, target)
    window = screen.window_of(target.id)
    site = Site(window.package, window.kind, surface_of(screen, target), context_labels(screen, target))
    address = NodeAddress(window.package, "", "", "", "", target.attrs.bounds, (), None)
    return classify(policy, Tap(point, address), site, locale)


def targetless(action, policy: Policy = POLICY, package: str = "test.app"):
    return classify(policy, action, Site(Package(package), WindowKind.APPLICATION, None, ()), "en-US")


def dialog(title: str, *buttons: str) -> Screen:
    return screen_of(
        node(
            "android.widget.FrameLayout",
            node("android.widget.TextView", text=title, bounds="[0,1500][1080,1600]"),
            *(
                node(
                    "android.widget.Button",
                    text=label,
                    clickable=True,
                    bounds=f"[{i * 540},1700][{i * 540 + 540},1800]",
                )
                for i, label in enumerate(buttons)
            ),
            bounds="[0,1400][1080,1900]",
        )
    )


def button(screen: Screen, label: str) -> Node:
    return consumer_of(screen, labelled(screen, label))


def test_a_settings_tile_is_judged_by_its_title_and_not_by_its_summary():
    settings = fixture_screen("settings-home")
    for title in ("Notifications", "Display", "Sounds and vibration", "Connections"):
        assert tap_on(settings, button(settings, title)) == Clear(ClearReason.NO_COMMIT_WORDS)
    summaries_read = merge((DEFAULT, parse_policy({"disable": ["default.preference-summary"]}, "c.toml")))
    verdict = tap_on(settings, button(settings, "Notifications"), summaries_read)
    assert isinstance(verdict, Commits) and verdict.effects == {Effect.SOCIAL}
    assert [(e.label, e.source) for e in verdict.evidence] == [
        ("Block, Allow, Do not disturb", Source.RECEIVER)
    ]


def test_a_neutral_affirmative_does_what_its_dialog_says():
    screen = dialog("Delete this post?", "Cancel", "OK")
    ok = tap_on(screen, button(screen, "OK"))
    assert isinstance(ok, Commits) and ok.effects == {Effect.DELETE}
    assert {e.source for e in ok.evidence} == {Source.CONTEXT}
    assert tap_on(screen, button(screen, "Cancel")) == Clear(ClearReason.NO_COMMIT_WORDS)
    harmless = dialog("An app is asking to turn on Bluetooth.", "Deny", "Allow")
    assert tap_on(harmless, button(harmless, "Allow")) == Clear(ClearReason.NO_COMMIT_WORDS)


def test_an_element_with_no_words_commits_unlabeled():
    screen = screen_of(node("android.widget.FrameLayout", node("android.widget.ImageButton", clickable=True)))
    verdict = tap_on(screen, screen.nodes[1])
    assert isinstance(verdict, Commits) and verdict.effects == {Effect.UNLABELED}


def test_an_exemption_clears_only_the_label_it_names_in_the_app_it_names():
    consumer = merge((DEFAULT, layer("examples/business_suite/policy.toml")))

    def later(package):
        return screen_of(
            node("android.widget.Button", text="Schedule for later", clickable=True, package=package)
        )

    in_app = later("com.facebook.pages.app")
    verdict = tap_on(in_app, in_app.nodes[0], consumer)
    assert verdict == Clear(ClearReason.EXEMPT, ("mbs.schedule-for-later",))
    elsewhere = later("test.app")
    assert tap_on(elsewhere, elsewhere.nodes[0], consumer).effects == {Effect.SCHEDULE}


def test_a_deny_rule_refuses_whatever_the_caller_grants_and_no_consumer_file_weakens_it():
    weakened = parse_policy(
        {
            "exempt": [{"id": "c.vpn", "labels": ["VPN"], "reason": "r"}],
            "ignore": [{"id": "c.ids", "node_ids": ["test.app:id/vpn"], "reason": "r"}],
        },
        "consumer.toml",
    )
    screen = screen_of(
        node("android.widget.Button", text="VPN", resource_id="test.app:id/vpn", clickable=True)
    )
    for policy in (merge((DEFAULT, PROFILE)), merge((DEFAULT, PROFILE, weakened))):
        verdict = tap_on(screen, screen.nodes[0], policy)
        assert isinstance(verdict, Denied) and verdict.rule == "j7.vpn-lockdown"
        everything = Grant(frozenset(Effect))
        with pytest.raises(Refusal) as refused:
            require(verdict, everything)
        assert refused.value.code is ErrorCode.DENIED
        assert refused.value.details["rule"] == "j7.vpn-lockdown"


def test_a_protected_package_cannot_be_stopped_and_its_app_info_buttons_are_denied():
    policy = merge((DEFAULT, PROFILE))
    stop = targetless(Stop(Package("hev.sockstun")), policy)
    assert isinstance(stop, Denied) and stop.rule == "profile.protect.hev.sockstun.stop"
    assert targetless(Stop(Package("com.android.settings")), policy) == Clear(ClearReason.NOT_LABELED_INPUT)
    assert targetless(Launch(Package("hev.sockstun")), policy) == Clear(ClearReason.NOT_LABELED_INPUT)
    info = dialog("SocksTun", "Force stop", "Uninstall")
    for label in ("Force stop", "Uninstall"):
        verdict = tap_on(info, button(info, label), policy)
        assert isinstance(verdict, Denied) and verdict.rule == "profile.protect.hev.sockstun.app-info"
    other = dialog("Calculator", "Force stop")
    assert tap_on(other, button(other, "Force stop"), policy).effects == {Effect.SYSTEM}


def test_keys_and_links_commit_by_their_own_rules():
    assert targetless(Key(KeyName.ENTER)).effects == {Effect.SEND}
    for key in (KeyName.BACK, KeyName.HOME, KeyName.RECENTS):
        assert targetless(Key(key)) == Clear(ClearReason.NOT_LABELED_INPUT)
    assert targetless(OpenUri("tel:5551234", None)).effects == {Effect.SEND}
    assert targetless(OpenUri("https://example.com/a", None)) == Clear(ClearReason.NOT_LABELED_INPUT)


def test_a_screen_in_a_language_without_rules_is_not_judged():
    settings = fixture_screen("settings-home")
    with pytest.raises(Refusal) as refused:
        tap_on(settings, button(settings, "Display"), locale="de-DE")
    assert refused.value.code is ErrorCode.LOCALE_UNSUPPORTED
    assert tap_on(settings, button(settings, "Display"), locale="it-IT") == Clear(ClearReason.NO_COMMIT_WORDS)


def test_a_grant_opens_exactly_the_effects_it_names():
    screen = screen_of(node("android.widget.Button", text="Schedule reel", clickable=True))
    verdict = tap_on(screen, screen.nodes[0])
    require(verdict, Grant(frozenset({Effect.SCHEDULE})))
    with pytest.raises(Refusal) as refused:
        require(verdict, Grant(frozenset({Effect.PUBLISH})))
    assert refused.value.code is ErrorCode.COMMIT_REFUSED
    assert refused.value.details == {
        "effects": ["schedule"],
        "granted": ["publish"],
        "evidence": [{"rule": "default.schedule", "source": "receiver", "label": "Schedule reel"}],
    }
    require(Clear(ClearReason.NO_COMMIT_WORDS), Grant.none())


def test_on_the_j7_the_connections_tile_is_denied_because_its_summary_names_airplane_mode():
    settings = fixture_screen("settings-home")
    policy = merge((DEFAULT, PROFILE))
    verdict = tap_on(settings, button(settings, "Connections"), policy)
    assert isinstance(verdict, Denied) and verdict.rule == "j7.vpn-lockdown"
    for title in ("Notifications", "Display", "Sounds and vibration"):
        assert tap_on(settings, button(settings, title), policy) == Clear(ClearReason.NO_COMMIT_WORDS)


def test_disabling_the_default_commit_rules_does_not_unprotect_a_package():
    weakening = parse_policy({"disable": ["default.system", "default.delete"]}, "consumer.toml")
    policy = merge((DEFAULT, PROFILE, weakening))
    info = dialog("SocksTun", "Force stop", "Uninstall")
    for label in ("Force stop", "Uninstall"):
        verdict = tap_on(info, button(info, label), policy)
        assert isinstance(verdict, Denied) and verdict.rule == "profile.protect.hev.sockstun.app-info"


TUNNEL = DeviceProfile(
    Serial("0a1b2c3d4e5f6a7b"),
    "phone",
    (ProtectedPackage(Package("com.example.tunnel"), ("SafeTunnel",), "Always-on lockdown VPN."),),
    (),
)
PROTECTS_TUNNEL = (Policy(frozenset(), protect_rules(TUNNEL, "phone.toml")), frozenset())
EXEMPTS_OK = {"exempt": [{"id": "x.ok", "labels": ["OK"], "reason": "OK closes dialogs here."}]}
EXEMPTS_DELETE = {"exempt": [{"id": "x.del", "labels": ["Delete"], "reason": "Delete is a heading here."}]}
BROKEN_FOR_CONSUMERS = pytest.mark.xfail(
    strict=True,
    reason="a denial reads the effects of the rules still in force, which a consumer's file changes",
)
BROKEN_FOR_THE_DEVICE = pytest.mark.xfail(
    strict=True, reason="a denial reads the effects of every withdrawn rule, whoever withdrew it"
)
OK_UNDER_A_DELETE = ("Delete SafeTunnel?", "OK")
DELETE_ON_THE_APP = ("SafeTunnel", "Delete")
"""The dialog a button sits in, and the button. The OK gets its effect from its dialog's words, and
the Delete button from its own."""
WEAKENINGS = {
    "disable the delete words, read through the dialog": (
        OK_UNDER_A_DELETE,
        {"disable": ["default.delete"]},
        BROKEN_FOR_CONSUMERS,
    ),
    "disable the affirmatives": (
        OK_UNDER_A_DELETE,
        {"disable": ["default.affirmative"]},
        BROKEN_FOR_CONSUMERS,
    ),
    "exempt OK": (OK_UNDER_A_DELETE, EXEMPTS_OK, BROKEN_FOR_CONSUMERS),
    "disable the delete words, read in the button": (
        DELETE_ON_THE_APP,
        {"disable": ["default.delete"]},
        None,
    ),
    "exempt Delete": (DELETE_ON_THE_APP, EXEMPTS_DELETE, None),
}


def weakened_tap(case, *, by_the_device):
    (title, label), doc, _ = WEAKENINGS[case]
    screen = dialog(title, "Cancel", label)
    layer_ = parse_policy(doc, "phone-policy.toml" if by_the_device else "consumer.toml", by_the_device)
    policy = merge((DEFAULT, PROTECTS_TUNNEL, layer_))
    assert tap_on(screen, button(screen, "Cancel"), policy) == Clear(ClearReason.NO_COMMIT_WORDS)
    return tap_on(screen, button(screen, label), policy)


def marked(case, by_the_device):
    own = WEAKENINGS[case][2]
    if by_the_device:
        return pytest.param(case, id=case, marks=() if own else BROKEN_FOR_THE_DEVICE)
    return pytest.param(case, id=case, marks=own or ())


def test_a_dialog_that_deletes_a_protected_app_is_denied_at_its_button():
    for title, label in (OK_UNDER_A_DELETE, DELETE_ON_THE_APP):
        screen = dialog(title, "Cancel", label)
        verdict = tap_on(screen, button(screen, label), merge((DEFAULT, PROTECTS_TUNNEL)))
        assert isinstance(verdict, Denied) and verdict.rule == "profile.protect.com.example.tunnel.app-info"


@pytest.mark.parametrize("case", [marked(case, False) for case in WEAKENINGS])
def test_a_consumer_layer_may_weaken_a_commit_and_never_a_denial(case):
    verdict = weakened_tap(case, by_the_device=False)
    assert isinstance(verdict, Denied), f"a consumer's file made the denied tap {verdict}"


@pytest.mark.parametrize("case", [marked(case, True) for case in WEAKENINGS])
def test_a_layer_of_the_device_may_weaken_what_its_own_denials_read(case):
    verdict = weakened_tap(case, by_the_device=True)
    assert not isinstance(verdict, Denied), "the device's own layer chose this, and the denial ignored it"


def test_on_the_j7_wi_fi_and_any_screen_that_shows_sockstun_are_denied():
    policy = merge((DEFAULT, PROFILE))
    wifi = screen_of(node("android.widget.Switch", content_desc="Wi-Fi", checkable=True, clickable=True))
    assert isinstance(tap_on(wifi, wifi.nodes[0], policy), Denied)
    vpn = dialog("SocksTun", "Disconnect", "Forget")
    for label in ("Disconnect", "Forget"):
        verdict = tap_on(vpn, button(vpn, label), policy)
        assert isinstance(verdict, Denied) and verdict.rule == "j7.sockstun-screens"
