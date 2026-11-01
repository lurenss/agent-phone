"""The commit table (`tests/policy/commit_table.toml`) replayed in every label field.

The engine judges the words of the element a touch lands on, wherever those words sit. Each row
of the table is planted in the tapped element's text, content-desc, hint, resource-id and class
name, and in the text of a child it owns, and each placement must give the row's effects."""

import tomllib

import pytest
from fakes import J7_SERIAL, FakePhone, info_for
from support import ROOT, FakeClock, node, screen_of

from agent_phone.cli.policy import DEFAULT_POLICY
from agent_phone.core.act.act import act
from agent_phone.core.act.hit import context_labels, plan_point, receiver_at
from agent_phone.core.act.intent import Click, Request
from agent_phone.core.act.ledger import Ledger
from agent_phone.core.context import Context
from agent_phone.core.device import Package
from agent_phone.core.labels import LabelField, normalized, surface_of, words
from agent_phone.core.outcome import Acted, ErrorCode, Refused
from agent_phone.core.phone import NodeAddress, Tap
from agent_phone.core.policy.engine import Clear, Commits, Site, classify
from agent_phone.core.policy.rules import (
    CommitRule,
    Effect,
    ExemptRule,
    InheritRule,
    Policy,
    merge,
    parse_policy,
)
from agent_phone.core.refs.resolve import RefTarget
from agent_phone.core.refs.store import SnapshotStore
from agent_phone.core.screen import Screen
from agent_phone.core.snapshot.capture import capture
from agent_phone.core.snapshot.snapshot import SettleState

TABLE_DOC = tomllib.loads((ROOT / "tests" / "policy" / "commit_table.toml").read_text(encoding="utf-8"))
TABLE = TABLE_DOC["case"]
DEFAULT = parse_policy(tomllib.loads(DEFAULT_POLICY.read_text(encoding="utf-8")), "default.toml")
POLICY = merge((DEFAULT,))
PLACEMENTS = ("text", "content_desc", "hint", "resource_id", "class_name", "child_text")
NO_CONSENT_YET = pytest.mark.xfail(strict=True, reason="the consent effect does not exist yet")


def awaiting_consent(effects) -> list:
    return [NO_CONSENT_YET] if "consent" in effects else []


def tapped(label: str, placement: str, question: str | None = None) -> Screen:
    """A full-screen app with one button, and the `question` above it when there is one. A
    neutral child text names the button in every placement, so a class name alone never leaves it
    unlabeled."""
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
    asked = [node("android.widget.TextView", text=question, bounds="[0,200][1080,300]")] if question else []
    return screen_of(
        node("android.widget.FrameLayout", node(cls, *children, **attrs), *asked, bounds="[0,0][1080,1920]")
    )


def verdict_of(screen: Screen, policy: Policy = POLICY):
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
    return classify(policy, Tap(point, address), site, "en-US")


def effects_of(verdict) -> set[str]:
    assert isinstance(verdict, Clear | Commits), verdict
    return {effect.value for effect in verdict.effects} if isinstance(verdict, Commits) else set()


CASES = [
    pytest.param(
        case["label"],
        placement,
        set(case["effects"]),
        id=f"{case['label']}-{placement}",
        marks=awaiting_consent(case["effects"]),
    )
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


@NO_CONSENT_YET
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


AFFIRMATIVES = TABLE_DOC["affirmative"]
NAMING_PLACEMENTS = ("text", "content_desc", "hint", "child_text")
AFFIRMATIVE_CASES = [
    pytest.param(
        row["label"],
        placement,
        row["question"],
        set(row["effects"]),
        id=f"{row['label']}-{placement}",
        marks=awaiting_consent(row["effects"]),
    )
    for row in AFFIRMATIVES
    for placement in NAMING_PLACEMENTS
]


@pytest.mark.parametrize(("label", "placement", "question", "effects"), AFFIRMATIVE_CASES)
def test_an_affirmative_under_a_question_that_commits_gives_its_own_effects_and_the_questions(
    label, placement, question, effects
):
    assert effects_of(verdict_of(tapped(label, placement, question))) == effects


@pytest.mark.parametrize(
    "label",
    [
        pytest.param(
            label,
            marks=awaiting_consent([e for case in TABLE if case["label"] == label for e in case["effects"]]),
        )
        for label in sorted({row["label"] for row in AFFIRMATIVES})
    ],
)
def test_the_words_of_a_class_or_an_id_are_no_affirmative(label):
    """An affirmative is a label the user reads: `ok` in a resource-id says nothing about what the
    button does, and the question under it is not read for it."""
    for placement in ("resource_id", "class_name"):
        own = {e for row in TABLE for e in row["effects"] if row["label"] == label}
        assert effects_of(verdict_of(tapped(label, placement, "Delete this post?"))) == own


def test_the_table_has_a_row_for_every_affirmative_of_the_default_policy():
    rows = {words(row["label"], LabelField.TEXT) for row in AFFIRMATIVES}
    for rule in POLICY.of_kind(InheritRule):
        for phrase in rule.words:
            assert phrase.words in rows, f"{rule.origin.rule} has no affirmative row for {phrase.words!r}"


DECLINES = TABLE_DOC["decline"]
DECLINE_CASES = [
    pytest.param(row["label"], placement, row["question"], id=f"{row['label']}-{placement}")
    for row in DECLINES
    for placement in NAMING_PLACEMENTS
]


@pytest.mark.parametrize(("label", "placement", "question"), DECLINE_CASES)
def test_a_decline_under_a_question_that_commits_stays_clear(label, placement, question):
    """The way out of a dialog stays open. A decline never reads its question, and one that holds
    a consent word is exempt."""
    assert effects_of(verdict_of(tapped(label, placement, question))) == set()


@NO_CONSENT_YET
def test_the_table_has_a_row_for_every_decline_the_default_policy_exempts():
    rows = {normalized(row["label"]) for row in DECLINES}
    exempt = [label for rule in POLICY.of_kind(ExemptRule) for label in rule.labels]
    assert exempt, "the default policy exempts the declines that hold a consent word"
    assert set(exempt) <= rows, f"no decline row for {sorted(set(exempt) - rows)}"


@NO_CONSENT_YET
def test_every_exempted_decline_would_give_consent_without_its_exemption():
    """A label in the exemption that commits nothing without it is dead data."""
    exempt = sorted(label for rule in POLICY.of_kind(ExemptRule) for label in rule.labels)
    assert exempt, "the default policy exempts the declines that hold a consent word"
    without = merge((DEFAULT, parse_policy({"disable": ["default.consent-declined"]}, "consumer.toml")))
    for label in exempt:
        assert effects_of(verdict_of(tapped(label, "text"), without)) == {"consent"}, label
