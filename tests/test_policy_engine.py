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


def layer(path, trusted=False):
    doc = tomllib.loads((ROOT / path).read_text(encoding="utf-8"))
    if trusted:
        doc = {key: value for key, value in doc.items() if key not in ("device", "protected")}
    return parse_policy(doc, path, trusted)


DEFAULT = layer("src/agent_phone/policy/default.toml", trusted=True)
POLICY = merge((DEFAULT,))
J7 = DeviceProfile(
    Serial("0a1b2c3d4e5f6a7b"),
    "j7",
    (ProtectedPackage(Package("hev.sockstun"), ("SocksTun",), "Always-on lockdown VPN."),),
    (),
)
PROFILE = (
    Policy(
        frozenset(),
        protect_rules(J7, "j7.toml") + layer("examples/devices/j7.toml", True)[0].rules,
        trusted=True,
    ),
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


OK_CONFIRMS = {"commit": [{"id": "c.ok", "effect": "confirm", "words": ["ok"], "reason": "A test commit."}]}


@pytest.mark.parametrize(
    ("title", "label", "consumer", "effects"),
    [
        ("Delete this post?", "OK", OK_CONFIRMS, {Effect.CONFIRM, Effect.DELETE}),
        ("Delete this post?", "Confirm", {}, {Effect.CONFIRM, Effect.DELETE}),
        ("Delete this post?", "Submit", {}, {Effect.CONFIRM, Effect.DELETE}),
    ],
    ids=["ok-under-a-consumer-confirm", "confirm", "submit"],
)
def test_a_button_keeps_its_own_effects_and_takes_those_of_its_dialog(title, label, consumer, effects):
    screen = dialog(title, "Cancel", label)
    policy = merge((DEFAULT, parse_policy(consumer, "consumer.toml")))
    verdict = tap_on(screen, button(screen, label), policy)
    assert isinstance(verdict, Commits) and verdict.effects == effects, (
        f"a button that does what its question says carries its effects too: {verdict}"
    )
    assert {e.source for e in verdict.evidence} == {Source.RECEIVER, Source.CONTEXT}


def test_a_button_whose_own_words_name_their_effect_does_not_take_its_dialogs_effects():
    screen = dialog("Delete this post?", "Cancel", "Send")
    verdict = tap_on(screen, button(screen, "Send"))
    assert isinstance(verdict, Commits) and verdict.effects == {Effect.SEND}, (
        f"'Send' says what it does, so the question under it adds nothing: {verdict}"
    )


def test_a_button_whose_words_also_confirm_takes_its_dialogs_effects_as_well():
    screen = dialog("Delete this post?", "Cancel", "Confirm and send")
    verdict = tap_on(screen, button(screen, "Confirm and send"))
    assert isinstance(verdict, Commits) and verdict.effects == {Effect.CONFIRM, Effect.SEND, Effect.DELETE}, (
        f"a confirm does what its question says, whatever else the button says: {verdict}"
    )


@pytest.mark.parametrize("description", ["OK, Button", "Allow,Button"])
def test_an_affirmative_described_with_a_role_suffix_does_what_its_dialog_says(description):
    screen = screen_of(
        node(
            "android.widget.FrameLayout",
            node("android.widget.TextView", text="Delete this post?", bounds="[0,1500][1080,1600]"),
            node("android.widget.Button", text="Cancel", clickable=True, bounds="[0,1700][540,1800]"),
            node(
                "android.widget.Button",
                content_desc=description,
                clickable=True,
                bounds="[540,1700][1080,1800]",
            ),
            bounds="[0,1400][1080,1900]",
        )
    )
    verdict = tap_on(screen, labelled_by_description(screen, description))
    shown = description.partition(",")[0]
    assert isinstance(verdict, Commits) and verdict.effects == {Effect.DELETE}, (
        f"the agent sees button {shown!r}, as it does for the text, and so should the gate: {verdict}"
    )
    assert {e.source for e in verdict.evidence} == {Source.CONTEXT}


def labelled_by_description(screen: Screen, description: str) -> Node:
    return next(n for n in screen.nodes if n.attrs.content_desc == description)


def test_a_role_word_beside_other_words_does_not_make_an_affirmative():
    screen = screen_of(
        node(
            "android.widget.FrameLayout",
            node("android.widget.TextView", text="Delete this post?", bounds="[0,1500][1080,1600]"),
            node(
                "android.widget.Button",
                content_desc="Not OK, Button",
                clickable=True,
                bounds="[0,1700][1080,1800]",
            ),
            bounds="[0,1400][1080,1900]",
        )
    )
    assert tap_on(screen, labelled_by_description(screen, "Not OK, Button")) == Clear(
        ClearReason.NO_COMMIT_WORDS
    )


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
PROTECTS_TUNNEL = (Policy(frozenset(), protect_rules(TUNNEL, "phone.toml"), trusted=True), frozenset())
EXEMPTS_OK = {"exempt": [{"id": "x.ok", "labels": ["OK"], "reason": "OK closes dialogs here."}]}
EXEMPTS_DELETE = {"exempt": [{"id": "x.del", "labels": ["Delete"], "reason": "Delete is a heading here."}]}
OK_UNDER_A_DELETE = ("Delete SafeTunnel?", "OK")
DELETE_ON_THE_APP = ("SafeTunnel", "Delete")
"""The dialog a button sits in, and the button. The OK gets its effect from its dialog's words, and
the Delete button from its own."""
WEAKENINGS = {
    "disable the delete words, read through the dialog": (OK_UNDER_A_DELETE, {"disable": ["default.delete"]}),
    "disable the affirmatives": (OK_UNDER_A_DELETE, {"disable": ["default.affirmative"]}),
    "exempt OK": (OK_UNDER_A_DELETE, EXEMPTS_OK),
    "disable the delete words, read in the button": (DELETE_ON_THE_APP, {"disable": ["default.delete"]}),
    "exempt Delete": (DELETE_ON_THE_APP, EXEMPTS_DELETE),
}


def weakened_tap(case, *, by_the_device):
    (title, label), doc = WEAKENINGS[case]
    screen = dialog(title, "Cancel", label)
    layer_ = parse_policy(doc, "phone-policy.toml" if by_the_device else "consumer.toml", by_the_device)
    policy = merge((DEFAULT, PROTECTS_TUNNEL, layer_))
    assert tap_on(screen, button(screen, "Cancel"), policy) == Clear(ClearReason.NO_COMMIT_WORDS)
    return tap_on(screen, button(screen, label), policy)


def test_a_dialog_that_deletes_a_protected_app_is_denied_at_its_button():
    for title, label in (OK_UNDER_A_DELETE, DELETE_ON_THE_APP):
        screen = dialog(title, "Cancel", label)
        verdict = tap_on(screen, button(screen, label), merge((DEFAULT, PROTECTS_TUNNEL)))
        assert isinstance(verdict, Denied) and verdict.rule == "profile.protect.com.example.tunnel.app-info"


@pytest.mark.parametrize("case", sorted(WEAKENINGS))
def test_a_consumer_layer_may_weaken_a_commit_and_never_a_denial(case):
    verdict = weakened_tap(case, by_the_device=False)
    assert isinstance(verdict, Denied), f"a consumer's file made the denied tap {verdict}"


@pytest.mark.parametrize("case", sorted(WEAKENINGS))
def test_a_layer_of_the_device_may_weaken_what_its_own_denials_read(case):
    verdict = weakened_tap(case, by_the_device=True)
    assert not isinstance(verdict, Denied), "the device's own layer chose this, and the denial ignored it"


CONSUMER_OK_CONFIRMS = parse_policy(OK_CONFIRMS, "consumer.toml")
CONSUMER_OK_CONFIRMS_AND_NO_DELETE = parse_policy(
    {**OK_CONFIRMS, "disable": ["default.delete"]}, "consumer.toml"
)


@pytest.mark.parametrize(
    ("label", "consumer"),
    [
        ("Confirm", None),
        ("Submit", None),
        ("OK", CONSUMER_OK_CONFIRMS),
        ("OK", CONSUMER_OK_CONFIRMS_AND_NO_DELETE),
    ],
    ids=["confirm", "submit", "ok-under-a-consumer-confirm", "ok-with-the-delete-words-disabled"],
)
def test_a_button_with_commit_words_of_its_own_is_denied_under_a_question_that_a_denial_names(
    label, consumer
):
    screen = dialog("Uninstall SafeTunnel?", "Cancel", label)
    layers = (DEFAULT, PROTECTS_TUNNEL, *(() if consumer is None else (consumer,)))
    verdict = tap_on(screen, button(screen, label), merge(layers))
    assert isinstance(verdict, Denied) and verdict.rule == "profile.protect.com.example.tunnel.app-info", (
        f"the button does what its question says, and the protection reads the question: got {verdict}"
    )


CONSUMER_CONFIRM_POSTS = parse_policy(
    {"commit": [{"id": "c.confirm-posts", "effect": "social", "words": ["confirm"], "reason": "r"}]},
    "consumer.toml",
)


@pytest.mark.parametrize(
    ("label", "consumer"),
    [("Confirm", CONSUMER_CONFIRM_POSTS), ("Confirm and send", None)],
    ids=["a-consumer-gives-confirm-a-second-effect", "a-confirm-that-also-sends"],
)
def test_a_button_whose_words_confirm_reads_its_question_whatever_else_they_say(label, consumer):
    screen = dialog("Uninstall SafeTunnel?", "Cancel", label)
    layers = (DEFAULT, PROTECTS_TUNNEL, *(() if consumer is None else (consumer,)))
    verdict = tap_on(screen, button(screen, label), merge(layers))
    assert isinstance(verdict, Denied) and verdict.rule == "profile.protect.com.example.tunnel.app-info", (
        f"a rule can add an effect to a confirming button and never take its question away: got {verdict}"
    )


J7_DENIES = merge((DEFAULT, PROFILE))
QUESTIONS = [("Turn off mobile data?", "OK"), ("Turn off Wi-Fi?", "OK"), ("Disconnect the VPN?", "Yes")]
WEAKENS_THE_AFFIRMATIVE = {
    "exempt-ok": {"exempt": [{"id": "c.ok", "labels": ["OK", "Yes"], "reason": "r"}]},
    "disable-the-affirmatives": {"disable": ["default.affirmative"]},
}


def test_a_button_that_says_a_word_a_denial_names_is_denied_and_a_cancel_beside_it_is_not():
    screen = dialog("Are you sure?", "Cancel", "Turn off mobile data")
    verdict = tap_on(screen, button(screen, "Turn off mobile data"), J7_DENIES)
    assert isinstance(verdict, Denied) and verdict.rule == "j7.vpn-lockdown"
    under = dialog("Turn off mobile data?", "Cancel", "OK")
    assert tap_on(under, button(under, "Cancel"), J7_DENIES) == Clear(ClearReason.NO_COMMIT_WORDS), (
        "Cancel does not do what its question says, and the way out of the dialog stays open"
    )


@pytest.mark.parametrize(("title", "label"), QUESTIONS)
def test_a_neutral_button_is_denied_by_the_words_of_its_question(title, label):
    screen = dialog(title, "Cancel", label)
    verdict = tap_on(screen, button(screen, label), J7_DENIES)
    assert isinstance(verdict, Denied) and verdict.rule == "j7.vpn-lockdown", (
        f"{label!r} does what {title!r} says, and the profile denies the network: got {verdict}"
    )
    assert {e.source for e in verdict.evidence} == {Source.CONTEXT}, "the denial names the question"


@pytest.mark.parametrize("case", sorted(WEAKENS_THE_AFFIRMATIVE))
def test_a_consumer_file_cannot_stop_a_denial_reading_the_question_of_a_neutral_button(case):
    screen = dialog("Turn off mobile data?", "Cancel", "OK")
    weakening = parse_policy(WEAKENS_THE_AFFIRMATIVE[case], "consumer.toml")
    verdict = tap_on(screen, button(screen, "OK"), merge((DEFAULT, PROFILE, weakening)))
    assert isinstance(verdict, Denied), f"a consumer's file made the denied tap {verdict}"


VERBS = [
    ("Turn off mobile data?", "Turn off"),
    ("Turn off Wi-Fi?", "Turn off"),
    ("Turn off Wi-Fi?", "Disable"),
    ("Disconnect the VPN?", "Disconnect"),
    ("Disattivare il Wi-Fi?", "Disattiva"),
    ("Interrompere la VPN?", "Interrompi"),
    ("Disconnettere la VPN?", "Disconnetti"),
]


@pytest.mark.parametrize(("title", "label"), VERBS)
def test_a_verb_that_takes_its_object_from_its_question_is_denied_when_the_question_names_the_network(
    title, label
):
    screen = dialog(title, "Cancel", label)
    verdict = tap_on(screen, button(screen, label), J7_DENIES)
    assert isinstance(verdict, Denied) and verdict.rule == "j7.vpn-lockdown", (
        f"{label!r} does to the object of {title!r} what it says, and the profile denies the network: "
        f"got {verdict}"
    )


def positive_button(title, label, **attrs):
    """A dialog with Cancel on the negative id and `label` on the positive one, which has `attrs`."""
    return screen_of(
        node(
            "android.widget.FrameLayout",
            node("android.widget.TextView", text=title, bounds="[0,1500][1080,1600]"),
            node(
                "android.widget.Button",
                text="Cancel",
                resource_id="android:id/button2",
                clickable=True,
                bounds="[0,1700][540,1800]",
            ),
            node(
                "android.widget.Button", text=label, clickable=True, bounds="[540,1700][1080,1800]", **attrs
            ),
            bounds="[0,1400][1080,1900]",
        )
    )


def test_the_positive_button_of_a_platform_dialog_does_what_its_question_says_whatever_it_is_called():
    asked = "Delete this post?"
    named = positive_button(asked, "Proceed", resource_id="android:id/button1")
    verdict = tap_on(named, button(named, "Proceed"))
    assert isinstance(verdict, Commits) and verdict.effects == {Effect.DELETE}, (
        f"android:id/button1 is the button that confirms the dialog's question: {verdict}"
    )
    network = positive_button("Turn off mobile data?", "Proceed", resource_id="android:id/button1")
    denied = tap_on(network, button(network, "Proceed"), J7_DENIES)
    assert isinstance(denied, Denied) and denied.rule == "j7.vpn-lockdown", f"got {denied}"


def test_a_button_with_no_such_id_is_not_taken_for_the_platforms_positive_button():
    asked = "Delete this post?"
    for attrs in ({}, {"resource_id": "test.app:id/button1"}, {"resource_id": "android:id/button2"}):
        screen = positive_button(asked, "Proceed", **attrs)
        assert tap_on(screen, button(screen, "Proceed")) == Clear(ClearReason.NO_COMMIT_WORDS), attrs


def test_on_the_j7_wi_fi_and_any_screen_that_shows_sockstun_are_denied():
    policy = merge((DEFAULT, PROFILE))
    wifi = screen_of(node("android.widget.Switch", content_desc="Wi-Fi", checkable=True, clickable=True))
    assert isinstance(tap_on(wifi, wifi.nodes[0], policy), Denied)
    vpn = dialog("SocksTun", "Disconnect", "Forget")
    forget = tap_on(vpn, button(vpn, "Forget"), policy)
    assert isinstance(forget, Denied) and forget.rule == "j7.sockstun-screens"
    disconnect = tap_on(vpn, button(vpn, "Disconnect"), policy)
    assert isinstance(disconnect, Denied) and disconnect.rule == "j7.sockstun", (
        "Disconnect takes its object from the question, so j7.sockstun, which comes before the screen "
        "rule and names the word in that question, denies it first"
    )
    assert {e.source for e in disconnect.evidence} == {Source.CONTEXT}
