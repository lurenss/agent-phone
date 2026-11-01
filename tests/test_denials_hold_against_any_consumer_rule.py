"""No consumer rule can turn a denied tap into anything else.

Two review rounds found five ways for a consumer layer to hide a dialog from a deny rule: disable,
exempt and ignore (round 1), an added commit rule (round 2), and an added second effect on a
confirm word. Each was closed on its own path. This test closes the class: for every dialog a
device's protection denies, it builds every one-rule consumer layer from the dialog's own words,
its ids and the rule ids loaded, and also layers that do all of it at once, and the tap must stay
denied under each. A layer the merge refuses (POLICY_INVALID) counts as held, because nothing is
sent with it.
"""

import re

import pytest
from support import consumer_of, labelled, node, screen_of
from test_policy_engine import DEFAULT, PROFILE, PROTECTS_TUNNEL, tap_on

from agent_phone.core.outcome import ErrorCode, Refusal
from agent_phone.core.policy.engine import Denied
from agent_phone.core.policy.rules import DenyRule, Effect, merge, parse_policy

IDS = ("android:id/message", "android:id/button1", "android:id/button2")
CASES = [
    *(
        ("tunnel", "Uninstall SafeTunnel?", label)
        for label in ("OK", "Confirm", "Submit", "Uninstall", "Yes")
    ),
    ("j7", "Turn off mobile data?", "OK"),
    ("j7", "Turn off mobile data?", "Turn off"),
    ("j7", "Turn off Wi-Fi?", "OK"),
    ("j7", "Disconnect the VPN?", "Disconnect"),
]
DEVICE = {"tunnel": PROTECTS_TUNNEL, "j7": PROFILE}


def dialog(title: str, positive: str, platform_ids: bool):
    """A platform dialog names its message and buttons with `android:id/` ids. An app that draws
    its own dialog often names none, and then only the words say what the button does."""
    ids = IDS if platform_ids else ("", "", "")
    return screen_of(
        node(
            "android.widget.FrameLayout",
            node("android.widget.TextView", text=title, resource_id=ids[0], bounds="[0,1500][1080,1600]"),
            node(
                "android.widget.Button",
                text="Cancel",
                resource_id=ids[2],
                clickable=True,
                bounds="[0,1700][540,1800]",
            ),
            node(
                "android.widget.Button",
                text=positive,
                resource_id=ids[1],
                clickable=True,
                bounds="[540,1700][1080,1800]",
            ),
            bounds="[0,1400][1080,1900]",
        )
    )


def words_of(*texts: str) -> list[str]:
    found = {w for text in texts for w in re.findall(r"[a-z0-9-]+", text.casefold())}
    return sorted(found | {"button", "textview", "button1", "button2", "message", "android"})


def one_rule_layers(title: str, positive: str, rule_ids: list[str]) -> dict[str, dict]:
    words = words_of(title, positive, "Cancel")
    layers: dict[str, dict] = {}
    for word in words:
        for effect in Effect:
            layers[f"commit {word}->{effect.value}"] = {
                "commit": [{"id": "c.r", "effect": effect.value, "words": [word], "reason": "r"}]
            }
        layers[f"inherit {word}"] = {"inherit": [{"id": "c.r", "words": [word], "reason": "r"}]}
    for label in (title, positive, "Cancel"):
        layers[f"exempt {label}"] = {"exempt": [{"id": "c.r", "labels": [label], "reason": "r"}]}
    for node_id in IDS:
        layers[f"ignore {node_id}"] = {"ignore": [{"id": "c.r", "node_ids": [node_id], "reason": "r"}]}
        layers[f"inherit id {node_id}"] = {"inherit": [{"id": "c.r", "node_ids": [node_id], "reason": "r"}]}
    for rule_id in rule_ids:
        layers[f"disable {rule_id}"] = {"disable": [rule_id]}
    for effect in Effect:
        layers[f"everything, commits ->{effect.value}"] = {
            "commit": [{"id": "c.all", "effect": effect.value, "words": words, "reason": "r"}],
            "exempt": [{"id": "c.x", "labels": [title, positive, "Cancel"], "reason": "r"}],
            "ignore": [{"id": "c.i", "node_ids": list(IDS), "reason": "r"}],
            "disable": rule_ids,
        }
    return layers


def verdict_under(device, doc: dict, screen, target):
    try:
        policy = merge((DEFAULT, device, parse_policy(doc, "consumer.toml")))
    except Refusal as refusal:
        assert refusal.code is ErrorCode.POLICY_INVALID, refusal
        return None
    return tap_on(screen, target, policy)


@pytest.mark.parametrize("platform_ids", [True, False], ids=["platform-dialog", "app-drawn-dialog"])
@pytest.mark.parametrize(("device", "title", "positive"), CASES, ids=[f"{t} {p}" for _, t, p in CASES])
def test_no_consumer_rule_turns_a_denied_tap_into_anything_else(device, title, positive, platform_ids):
    screen = dialog(title, positive, platform_ids)
    target = consumer_of(screen, labelled(screen, positive))
    base = merge((DEFAULT, DEVICE[device]))
    assert isinstance(tap_on(screen, target, base), Denied), "the case must start denied"
    rule_ids = sorted({rule.origin.rule for rule in base.rules if not isinstance(rule, DenyRule)})
    layers = one_rule_layers(title, positive, rule_ids)
    opened = {
        name: verdict
        for name, doc in layers.items()
        if (verdict := verdict_under(DEVICE[device], doc, screen, target)) is not None
        and not isinstance(verdict, Denied)
    }
    assert not opened, (
        f"{len(opened)} of {len(layers)} consumer layers opened {positive!r} under {title!r}: "
        + "; ".join(f"{name}: {verdict}" for name, verdict in list(opened.items())[:5])
    )
