"""No consumer rule can turn a denied tap into anything else.

Two review rounds found five ways for a consumer layer to hide a dialog from a deny rule: disable,
exempt and ignore (round 1), an added commit rule (round 2), and an added second effect on a
confirm word. Each was closed on its own path. This test closes the class: for every dialog a
device's protection denies, it builds every one-rule consumer layer from the dialog's own words,
its ids and the rule ids loaded, and also layers that do all of it at once, and the tap must stay
denied under each. A layer the merge refuses (POLICY_INVALID) counts as held, because nothing is
sent with it.

The permission mode is a second layer that must not weaken a denial, so the same layers run again
through `act()` in each mode. Under `dangerously-skip` the tap is sent with no grant at all, and a
denial that holds there holds in the mode that asks for one.
"""

import re

import pytest
from fakes import J7_SERIAL, FakePhone, info_for
from support import FakeClock, consumer_of, labelled, node, screen_of
from test_policy_engine import DEFAULT, PROFILE, PROTECTS_TUNNEL, tap_on

from agent_phone.cli.settings import Settings
from agent_phone.core.act.act import act
from agent_phone.core.act.intent import Click, Request
from agent_phone.core.act.ledger import Ledger
from agent_phone.core.context import Context
from agent_phone.core.outcome import Acted, ErrorCode, Refusal, Refused
from agent_phone.core.policy.engine import Denied, Grant
from agent_phone.core.policy.rules import DenyRule, Effect, merge, parse_policy
from agent_phone.core.refs.resolve import RefTarget
from agent_phone.core.refs.store import SnapshotStore
from agent_phone.core.snapshot.capture import capture
from agent_phone.core.snapshot.snapshot import SettleState

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


MODES = ["ask", "dangerously-skip"]
NO_MODES_YET = pytest.mark.xfail(strict=True, reason="the permission modes do not exist yet")
CANCEL_SENDS = {"commit": [{"id": "c.cancel", "effect": "send", "words": ["cancel"], "reason": "r"}]}


class Held:
    """One tap judged by `act()` on a fake phone, under one policy, in one mode."""

    def __init__(self, root, screen, mode, serial: int = 0) -> None:
        self.root, self.screen, self.mode, self.serial = root, screen, mode, serial
        info = info_for(J7_SERIAL)
        first = Context(
            FakePhone(info, screen),
            info,
            None,
            merge((DEFAULT,)),
            SnapshotStore(root),
            Ledger(root / "taken", info.identity),
            FakeClock(),
            mode,
        )
        self.taken = capture(first, first.phone.read(), settled=SettleState.SETTLED)

    def tap(self, policy, label: str, grant: Grant):
        """The outcome, and the inputs the fake phone received. Each tap has its own ledger, so an
        input that got through does not turn the taps after it into STALE_REF."""
        self.serial += 1
        info = info_for(J7_SERIAL)
        phone = FakePhone(info, self.screen)
        ctx = Context(
            phone,
            info,
            None,
            policy,
            SnapshotStore(self.root),
            Ledger(self.root / f"tap{self.serial}", info.identity),
            FakeClock(),
            self.mode,
        )
        [line] = [line for line in self.taken.lines if line.name == label]
        outcome = act(ctx, Request(Click(RefTarget(self.taken.ref(line.ref))), grant))
        return outcome, phone.permits


@NO_MODES_YET
@pytest.mark.parametrize("platform_ids", [True, False], ids=["platform-dialog", "app-drawn-dialog"])
@pytest.mark.parametrize(("device", "title", "positive"), CASES, ids=[f"{t} {p}" for _, t, p in CASES])
@pytest.mark.parametrize("value", MODES)
def test_no_consumer_rule_lets_a_denied_tap_through_in_either_mode(
    tmp_path, value, device, title, positive, platform_ids
):
    mode = Settings.from_environment({"AGENT_PHONE_PERMISSION_MODE": value}).permission_mode
    held = Held(tmp_path, dialog(title, positive, platform_ids), mode)
    base = merge((DEFAULT, DEVICE[device]))
    nothing, everything = Grant.none(), Grant(frozenset(Effect))
    for grant in (nothing, everything):
        outcome, sent = held.tap(base, positive, grant)
        assert isinstance(outcome, Refused) and outcome.code is ErrorCode.DENIED and sent == []
    rule_ids = sorted({rule.origin.rule for rule in base.rules if not isinstance(rule, DenyRule)})
    layers = one_rule_layers(title, positive, rule_ids)
    grant = nothing if value == "dangerously-skip" else everything
    opened = {}
    for name, doc in layers.items():
        try:
            policy = merge((DEFAULT, DEVICE[device], parse_policy(doc, "consumer.toml")))
        except Refusal as refusal:
            assert refusal.code is ErrorCode.POLICY_INVALID, refusal
            continue
        outcome, sent = held.tap(policy, positive, grant)
        if sent or not (isinstance(outcome, Refused) and outcome.code is ErrorCode.DENIED):
            opened[name] = "SENT" if sent else getattr(outcome, "code", outcome)
    assert not opened, (
        f"in mode {value}, {len(opened)} of {len(layers)} consumer layers opened {positive!r} "
        f"under {title!r}: " + "; ".join(f"{name}: {how}" for name, how in list(opened.items())[:5])
    )


@NO_MODES_YET
@pytest.mark.parametrize("value", MODES)
def test_the_mode_is_live_in_this_harness_a_commit_goes_out_only_in_skip_mode(tmp_path, value):
    """The control for the sweep above: with the mode set as the sweep sets it, a tap that commits
    and has no grant is sent in `dangerously-skip` and refused in `ask`."""
    mode = Settings.from_environment({"AGENT_PHONE_PERMISSION_MODE": value}).permission_mode
    held = Held(tmp_path, dialog("Are you sure?", "OK", True), mode)
    policy = merge((DEFAULT, parse_policy(CANCEL_SENDS, "consumer.toml")))
    outcome, sent = held.tap(policy, "Cancel", Grant.none())
    if value == "dangerously-skip":
        assert isinstance(outcome, Acted) and len(sent) == 1
    else:
        assert isinstance(outcome, Refused) and outcome.code is ErrorCode.COMMIT_REFUSED and sent == []
