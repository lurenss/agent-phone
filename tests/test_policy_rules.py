import tomllib

import pytest
from support import ROOT

from agent_phone.core.device import Package
from agent_phone.core.labels import LabelField, words
from agent_phone.core.outcome import ErrorCode, Refusal
from agent_phone.core.phone import KeyName
from agent_phone.core.policy.rules import (
    CommitRule,
    DenyRule,
    Effect,
    ExemptRule,
    Phrase,
    Scope,
    merge,
    parse_policy,
)
from agent_phone.core.screen import WindowKind

DEFAULT = "src/agent_phone/policy/default.toml"
INSTAGRAM = "examples/instagram/policy.toml"
BUSINESS_SUITE = "examples/business_suite/policy.toml"
PROFILE = "examples/devices/j7.toml"


def load(path, trusted=False):
    doc = tomllib.loads((ROOT / path).read_text())
    if trusted:
        doc = {key: value for key, value in doc.items() if key not in ("device", "protected")}
    return parse_policy(doc, path, trusted=trusted)


def refuses_to_disable(layers, rule_id):
    try:
        merge((*layers, parse_policy({"disable": [rule_id]}, "consumer.toml")))
    except Refusal as refused:
        return refused.code is ErrorCode.POLICY_INVALID
    return False


def rule(policy, id):
    return next(r for r in policy.rules if r.origin.rule == id)


def test_the_default_policy_parses_into_rules_with_phrases_split_like_labels():
    policy, disabled = load(DEFAULT)
    assert policy.languages == {"en", "it"} and disabled == set()
    publish = rule(policy, "default.publish")
    assert isinstance(publish, CommitRule) and publish.effect is Effect.PUBLISH
    assert Phrase(("post",), anchored=True) in publish.words
    assert Phrase(("go", "live"), anchored=False) in publish.words
    delete = rule(policy, "default.delete")
    assert Phrase(words("Clear All", LabelField.TEXT), anchored=False) in delete.words
    assert rule(policy, "default.key.enter").keys == {KeyName.ENTER}
    assert rule(policy, "default.uri.contact").uri_schemes >= {"tel", "sms", "mailto"}
    assert rule(policy, "default.preference-summary").node_ids == {"android:id/summary"}


def test_example_policies_scope_their_rules_to_their_app():
    policy, _ = load(BUSINESS_SUITE)
    exempt = rule(policy, "mbs.schedule-for-later")
    assert isinstance(exempt, ExemptRule) and exempt.labels == {"schedule for later"}
    assert exempt.scope.packages == {"com.facebook.pages.app"}


def test_shipped_layers_merge_in_order_and_the_profile_deny_is_marked():
    profile, _ = load(PROFILE, trusted=True)
    layers = (load(DEFAULT), (profile, frozenset()), load(INSTAGRAM), load(BUSINESS_SUITE))
    merged = merge(layers)
    ids = [r.origin.rule for r in merged.rules]
    sources = [r.origin.source for r in merged.rules]
    assert list(dict.fromkeys(sources)) == [DEFAULT, PROFILE, INSTAGRAM, BUSINESS_SUITE]
    assert sources == sorted(sources, key=[DEFAULT, PROFILE, INSTAGRAM, BUSINESS_SUITE].index)
    assert len(ids) == len(set(ids)) == 20
    deny = {r.origin.rule: refuses_to_disable(layers, r.origin.rule) for r in merged.of_kind(DenyRule)}
    assert deny == {
        "j7.vpn-lockdown": True,
        "j7.sockstun": True,
        "j7.sockstun-screens": True,
        "ig.no-live": False,
    }
    assert merged.languages == {"en", "it"}


def test_a_later_file_disables_an_earlier_rule_by_id():
    consumer = parse_policy({"disable": ["default.social"]}, "consumer.toml")
    merged = merge((load(DEFAULT), consumer))
    assert "default.social" not in {r.origin.rule for r in merged.rules}
    assert "default.publish" in {r.origin.rule for r in merged.rules}


@pytest.mark.parametrize(
    "layers",
    [
        pytest.param(
            lambda: (load(PROFILE, True), parse_policy({"disable": ["j7.vpn-lockdown"]}, "c.toml")),
            id="profile deny",
        ),
        pytest.param(
            lambda: (load(DEFAULT), parse_policy({"disable": ["default.socail"]}, "c.toml")), id="unknown id"
        ),
        pytest.param(lambda: (load(DEFAULT), load(DEFAULT)), id="id defined twice"),
    ],
)
def test_merge_refuses_to_unprotect_a_device_or_shadow_a_rule(layers):
    with pytest.raises(Refusal) as refused:
        merge(layers())
    assert refused.value.code is ErrorCode.POLICY_INVALID


COMMIT = {"id": "t.send", "effect": "send", "words": ["send"], "reason": "Sends."}


@pytest.mark.parametrize(
    ("doc", "table", "field"),
    [
        ({"comit": []}, "document", "comit"),
        ({"commit": {"id": "t"}}, "document", "commit"),
        ({"commit": [{**COMMIT, "efect": "send"}]}, "commit", "efect"),
        ({"commit": [{**COMMIT, "effect": "post"}]}, "commit", "effect"),
        ({"commit": [{**COMMIT, "words": []}]}, "commit", "words"),
        ({"commit": [{**COMMIT, "words": ["^", "send"]}]}, "commit", "words"),
        ({"commit": [{**COMMIT, "words": [7]}]}, "commit", "words"),
        ({"commit": [{k: v for k, v in COMMIT.items() if k != "words"}]}, "commit", "words"),
        ({"commit": [{k: v for k, v in COMMIT.items() if k != "reason"}]}, "commit", "reason"),
        ({"commit": [{**COMMIT, "window_kinds": ["popup"]}]}, "commit", "window_kinds"),
        ({"commit": [{**COMMIT, "keys": ["volume_up"]}]}, "commit", "keys"),
        ({"commit": [COMMIT, {**COMMIT, "words": ["reply"]}]}, "commit", "id"),
        ({"exempt": [{"id": "t.e", "reason": "r"}]}, "exempt", "labels"),
        ({"ignore": [{"id": "t.i", "reason": "r", "node_ids": []}]}, "ignore", "node_ids"),
        ({"inherit": [{"id": "t.a", "reason": "r"}]}, "inherit", "words"),
        ({"inherit": [{"id": "t.a", "reason": "r", "words": ["ok"], "node_ids": []}]}, "inherit", "node_ids"),
        ({"deny": [{"id": "t.d", "reason": "r"}]}, "deny", "words"),
        ({"deny": [{"id": "t.d", "reason": "r", "effects": ["everything"]}]}, "deny", "effects"),
        ({"languages": "en"}, "document", "languages"),
    ],
)
def test_an_invalid_policy_names_the_file_the_table_and_the_field(doc, table, field):
    with pytest.raises(Refusal) as refused:
        parse_policy(doc, "consumer.toml")
    assert refused.value.code is ErrorCode.POLICY_INVALID
    assert refused.value.details == {"source": "consumer.toml", "table": table, "field": field}
    assert refused.value.message.startswith("consumer.toml: ")


def test_a_scope_applies_where_every_set_it_names_holds():
    everywhere = Scope(frozenset(), frozenset(), frozenset())
    one_app = Scope(frozenset({Package("test.app")}), frozenset({WindowKind.APPLICATION}), frozenset({"en"}))
    assert everywhere.applies(Package("other.app"), WindowKind.SYSTEM, "it")
    assert one_app.applies(Package("test.app"), WindowKind.APPLICATION, "en")
    assert not one_app.applies(Package("other.app"), WindowKind.APPLICATION, "en")
    assert not one_app.applies(Package("test.app"), WindowKind.SYSTEM, "en")
    assert not one_app.applies(Package("test.app"), WindowKind.APPLICATION, "it")


def test_an_inherit_rule_names_words_or_resource_ids_and_may_name_both():
    by_id = {"id": "t.id", "reason": "r", "node_ids": ["android:id/button1"]}
    by_both = {"id": "t.both", "reason": "r", "words": ["ok"], "node_ids": ["android:id/button1"]}
    policy, _ = parse_policy({"inherit": [by_id, by_both]}, "consumer.toml")
    only_id, both = policy.rules
    assert only_id.words == () and only_id.node_ids == {"android:id/button1"}
    assert both.words == (Phrase(("ok",), anchored=False),) and both.node_ids == {"android:id/button1"}
