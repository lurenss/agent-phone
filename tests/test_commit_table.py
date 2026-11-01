"""The commit table (`tests/policy/commit_table.toml`) replayed in every label field.

The engine judges the words of the element a touch lands on, wherever those words sit. Each row
of the table is planted in the tapped element's text, content-desc, hint, resource-id and class
name, and in the text of a child it owns, and each placement must give the row's effects."""

import tomllib

import pytest
from fakes import J7_SERIAL, FakePhone, info_for
from support import ROOT, FakeClock, node, screen_of

from agent_phone.cli.driver import DEFAULT_POLICY
from agent_phone.core.act.act import act
from agent_phone.core.act.hit import context_labels, plan_point, receiver_at
from agent_phone.core.act.intent import Click, Request
from agent_phone.core.act.ledger import Ledger
from agent_phone.core.context import Context
from agent_phone.core.device import Package
from agent_phone.core.labels import LabelField, surface_of, words
from agent_phone.core.outcome import Acted, ErrorCode, Refused
from agent_phone.core.phone import NodeAddress, Tap
from agent_phone.core.policy.engine import Clear, Commits, Site, classify
from agent_phone.core.policy.rules import CommitRule, Effect, merge, parse_policy
from agent_phone.core.refs.resolve import RefTarget
from agent_phone.core.refs.store import SnapshotStore
from agent_phone.core.screen import Screen
from agent_phone.core.snapshot.capture import capture
from agent_phone.core.snapshot.snapshot import SettleState

TABLE = tomllib.loads((ROOT / "tests" / "policy" / "commit_table.toml").read_text(encoding="utf-8"))["case"]
POLICY = merge((parse_policy(tomllib.loads(DEFAULT_POLICY.read_text(encoding="utf-8")), "default.toml"),))
PLACEMENTS = ("text", "content_desc", "hint", "resource_id", "class_name", "child_text")


def tapped(label: str, placement: str) -> Screen:
    """A full-screen app with one button. A neutral child text names the button in every
    placement, so a class name alone never leaves it unlabeled."""
    tokens = words(label, LabelField.TEXT)
    attrs: dict[str, object] = {"clickable": True, "bounds": "[0,0][400,100]"}
    cls = "android.widget.Button"
    children = [node("android.widget.TextView", text="Item", bounds="[0,0][200,100]")]
    match placement:
        case "resource_id":
            attrs["resource_id"] = "test.app:id/" + "_".join(tokens)
        case "class_name":
            cls = "test.app." + "".join(token.capitalize() for token in tokens)
        case "child_text":
            children.append(node("android.widget.TextView", text=label, bounds="[200,0][400,100]"))
        case _:
            attrs[placement] = label
    return screen_of(
        node("android.widget.FrameLayout", node(cls, *children, **attrs), bounds="[0,0][1080,1920]")
    )


def verdict_of(screen: Screen):
    button = screen.nodes[1]
    point = plan_point(screen, button)
    receiver = screen.node(receiver_at(screen, screen.windows[0], point))
    site = Site(
        Package("test.app"),
        screen.windows[0].kind,
        surface_of(screen, receiver),
        context_labels(screen, receiver),
    )
    address = NodeAddress(Package("test.app"), "", "", "", "", button.attrs.bounds, (0,), None)
    return classify(POLICY, Tap(point, address), site, "en-US")


def effects_of(verdict) -> set[str]:
    assert isinstance(verdict, Clear | Commits), verdict
    return {effect.value for effect in verdict.effects} if isinstance(verdict, Commits) else set()


CASES = [
    pytest.param(case["label"], placement, set(case["effects"]), id=f"{case['label']}-{placement}")
    for case in TABLE
    for placement in PLACEMENTS
]


@pytest.mark.parametrize(("label", "placement", "effects"), CASES)
def test_every_placement_of_a_label_gives_the_effects_of_its_row(label, placement, effects):
    assert effects_of(verdict_of(tapped(label, placement))) == effects


def test_the_table_has_a_row_for_every_phrase_of_the_default_policy():
    rows = [(words(case["label"], LabelField.TEXT), set(case["effects"])) for case in TABLE]
    for rule in POLICY.of_kind(CommitRule):
        for phrase in rule.words:
            n = len(phrase.words)
            covered = any(
                rule.effect.value in effects
                and any(
                    tokens[i : i + n] == phrase.words
                    for i in ((0,) if phrase.anchored else range(len(tokens)))
                )
                for tokens, effects in rows
            )
            assert covered, f"{rule.origin.rule} has no table row for {' '.join(phrase.words)!r}"


def test_the_table_lists_only_effects_that_exist():
    known = {effect.value for effect in Effect}
    assert all(set(case["effects"]) <= known for case in TABLE)


@pytest.mark.parametrize(("label", "placement", "effects"), CASES)
def test_a_click_on_any_placement_of_a_commit_sends_nothing(tmp_path, label, placement, effects):
    info = info_for(J7_SERIAL)
    phone = FakePhone(info, tapped(label, placement))
    ctx = Context(
        phone, info, None, POLICY, SnapshotStore(tmp_path), Ledger(tmp_path, info.identity), FakeClock()
    )
    taken = capture(ctx, phone.read(), settled=SettleState.SETTLED)
    outcome = act(ctx, Request(Click(RefTarget(taken.ref(1)))))
    if effects:
        assert isinstance(outcome, Refused) and outcome.code is ErrorCode.COMMIT_REFUSED
        assert set(outcome.details["effects"]) == effects and phone.permits == []
    else:
        assert isinstance(outcome, Acted) and len(phone.permits) == 1
