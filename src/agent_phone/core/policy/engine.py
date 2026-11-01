"""The policy engine: what an input would do, judged from what it would land on.

The engine never sees how the caller named the target. It is given the `Site` that act()
derived from the live screen: the node that will receive the touch at the planned point
(`act/hit.py`), that node's whole label surface (every label field of it and of the
descendants it owns, `labels.surface_of`), and the context around it. A ref, a query by text,
a query by resource-id and a raw point that land on the same node get the same verdict. That
is the property the commit table tests: each commit phrase is planted in text, in
content-desc, in hint, in a resource-id, in a class name and in a child's text, and every
placement must give the same verdict.

Commit rules read the labels that `ignore` and `exempt` rules leave. Deny rules read every
label, because those two kinds can come from a consumer's file, and no consumer may weaken a
deny rule by ignoring or exempting the words it names.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import Enum

from agent_phone.core.device import Package
from agent_phone.core.labels import Label, LabelField, Surface, normalized, words
from agent_phone.core.outcome import ErrorCode, Refusal
from agent_phone.core.phone import Activate, InputAction, Key, LongPress, OpenUri, Stop, Tap
from agent_phone.core.policy.rules import (
    CommitRule,
    DenyRule,
    Effect,
    ExemptRule,
    IgnoreRule,
    InheritRule,
    Phrase,
    Policy,
    RuleId,
    Scope,
)
from agent_phone.core.screen import WindowKind


@dataclass(frozen=True, slots=True)
class Site:
    """`receiver` is None when no touch consumer is under the point (a blank area), and for an
    input that lands on no node, such as a key, which goes to the window that has focus.

    `context` is the text the receiver sits in: the whole window when the surface is a
    dialog, else the whole surface. The receiver's own labels are not repeated in it.
    """

    package: Package
    window_kind: WindowKind
    receiver: Surface | None
    context: tuple[Label, ...]


class Source(Enum):
    RECEIVER = "receiver"
    CONTEXT = "context"
    UNLABELED = "unlabeled"
    KEY = "key"
    URI = "uri"
    PACKAGE = "package"


@dataclass(frozen=True, slots=True)
class Evidence:
    rule: RuleId | None
    source: Source
    label: str | None
    phrase: Phrase | None


class ClearReason(Enum):
    NO_RECEIVER = "no_receiver"
    NO_COMMIT_WORDS = "no_commit_words"
    EXEMPT = "exempt"
    NOT_LABELED_INPUT = "not_labeled_input"


@dataclass(frozen=True, slots=True)
class Clear:
    reason: ClearReason
    exempted_by: tuple[RuleId, ...] = ()


@dataclass(frozen=True, slots=True)
class Commits:
    effects: frozenset[Effect]
    evidence: tuple[Evidence, ...]


@dataclass(frozen=True, slots=True)
class Denied:
    rule: RuleId
    reason: str
    source: str
    evidence: tuple[Evidence, ...]


Verdict = Clear | Commits | Denied


@dataclass(frozen=True, slots=True)
class Grant:
    """What the caller allowed for this one input. `--commit schedule` is Grant({SCHEDULE})."""

    effects: frozenset[Effect]

    @staticmethod
    def none() -> Grant:
        return Grant(frozenset())

    def allows(self, verdict: Verdict) -> bool:
        match verdict:
            case Clear():
                return True
            case Commits(effects=effects):
                return effects <= self.effects
            case Denied():
                return False


Found = tuple[Effect, Evidence]


def language_of(locale: str) -> str:
    """`en-US` -> `en`, the form policy files name languages in."""
    return locale.partition("-")[0].casefold()


def classify(policy: Policy, action: InputAction, site: Site | None, locale: str) -> Verdict:
    """Pure. `site` is None only for an input that lands nowhere at all; act() passes the
    window that has focus for keys, launches and the like, so app-scoped rules apply to them.

    Raises `Refusal(LOCALE_UNSUPPORTED)` when a labeled input arrives and the device's language
    is not in `policy.languages`.
    """
    language = language_of(locale)

    def rules[R: CommitRule | ExemptRule | IgnoreRule | InheritRule | DenyRule](kind: type[R]) -> list[R]:
        return [rule for rule in policy.of_kind(kind) if in_scope(rule.scope, site, language)]

    commits = rules(CommitRule)
    found: list[Found] = []
    raw: list[Found] = []
    exempted: list[RuleId] = []
    receiver: Sequence[Label] = ()
    context: Sequence[Label] = ()
    labeled = isinstance(action, Tap | LongPress | Activate)
    if labeled:
        if language not in policy.languages:
            raise Refusal(
                ErrorCode.LOCALE_UNSUPPORTED,
                f"The device language {locale!r} has no policy rules, so agent-phone cannot read "
                f"what this input would do. The rules cover {', '.join(sorted(policy.languages))}.",
                {"locale": locale, "languages": sorted(policy.languages)},
            )
        if site is not None and site.receiver is not None:
            receiver, context = site.receiver.labels, site.context
            found, exempted = judge_receiver(
                commits, rules(IgnoreRule), rules(ExemptRule), rules(InheritRule), receiver, context
            )
            raw = phrases_in(commits, receiver, Source.RECEIVER)
    match action:
        case Key(key=key):
            found = [found_by(rule, Source.KEY, key.value) for rule in commits if key in rule.keys]
        case OpenUri(uri=uri):
            scheme = uri.partition(":")[0].casefold()
            found = [found_by(rule, Source.URI, uri) for rule in commits if scheme in rule.uri_schemes]
    effects = {effect for effect, _ in found}
    for rule in rules(DenyRule):
        evidence = denial(rule, action, receiver, context, effects | {effect for effect, _ in raw})
        if evidence is not None:
            return Denied(rule.origin.rule, rule.origin.reason, rule.origin.source, evidence)
    if effects:
        return Commits(frozenset(effects), tuple(evidence for _, evidence in found))
    if not labeled:
        return Clear(ClearReason.NOT_LABELED_INPUT)
    if site is None or site.receiver is None:
        return Clear(ClearReason.NO_RECEIVER)
    if exempted:
        return Clear(ClearReason.EXEMPT, tuple(dict.fromkeys(exempted)))
    return Clear(ClearReason.NO_COMMIT_WORDS)


def found_by(rule: CommitRule, source: Source, label: str) -> Found:
    return rule.effect, Evidence(rule.origin.rule, source, label, None)


def in_scope(scope: Scope, site: Site | None, language: str) -> bool:
    if site is None:
        unscoped = not scope.packages and not scope.window_kinds
        return unscoped and (not scope.languages or language in scope.languages)
    return scope.applies(site.package, site.window_kind, language)


def judge_receiver(
    commits: Sequence[CommitRule],
    ignores: Sequence[IgnoreRule],
    exempts: Sequence[ExemptRule],
    inherits: Sequence[InheritRule],
    receiver: Sequence[Label],
    context: Sequence[Label],
) -> tuple[list[Found], list[RuleId]]:
    """The effects of a tap on `receiver`, and the exempt rules that removed a label from it.

    A receiver with no naming label and no resource-id left after the ignore rules is
    unlabeled: nothing says what it does. A neutral affirmative ("OK") takes the effects of the
    words around it."""
    ignored = {node_id for rule in ignores for node_id in rule.node_ids}
    own = [label for label in receiver if label.node_resource_id not in ignored]
    around = [label for label in context if label.node_resource_id not in ignored]
    exempted: list[RuleId] = []

    def kept(labels: Iterable[Label]) -> list[Label]:
        left = []
        for label in labels:
            by = [rule.origin.rule for rule in exempts if normalized(label.value) in rule.labels]
            exempted.extend(by)
            if not by:
                left.append(label)
        return left

    own_kept = kept(own)
    found = phrases_in(commits, own_kept, Source.RECEIVER)
    if not any(label.naming or label.field is LabelField.RESOURCE_ID for label in own):
        found.append((Effect.UNLABELED, Evidence(None, Source.UNLABELED, None, None)))
    if not found and is_affirmative(inherits, own_kept):
        found = phrases_in(commits, kept(around), Source.CONTEXT)
    return found, exempted


def is_affirmative(inherits: Sequence[InheritRule], labels: Sequence[Label]) -> bool:
    """True when a naming label is, as a whole, one of the inherit rules' words."""
    affirmatives = {phrase.words for rule in inherits for phrase in rule.words}
    return any(label.naming and words(label.value, label.field) in affirmatives for label in labels)


def phrases_in(rules: Sequence[CommitRule], labels: Sequence[Label], source: Source) -> list[Found]:
    found = []
    for rule in rules:
        for label in labels:
            phrase = phrase_in(rule.words, label)
            if phrase is not None:
                found.append((rule.effect, Evidence(rule.origin.rule, source, label.value, phrase)))
    return found


def phrase_in(phrases: Sequence[Phrase], label: Label) -> Phrase | None:
    tokens = words(label.value, label.field)
    for phrase in phrases:
        n = len(phrase.words)
        starts = (0,) if phrase.anchored else range(len(tokens) - n + 1)
        if any(tokens[start : start + n] == phrase.words for start in starts):
            return phrase
    return None


def denial(
    rule: DenyRule,
    action: InputAction,
    receiver: Sequence[Label],
    context: Sequence[Label],
    effects: set[Effect],
) -> tuple[Evidence, ...] | None:
    """The evidence for `rule` when every condition it names holds, else None."""
    evidence: list[Evidence] = []
    readings = ((rule.words, receiver, Source.RECEIVER), (rule.context_words, context, Source.CONTEXT))
    for phrases, labels, source in readings:
        if not phrases:
            continue
        hits = [(label, phrase) for label in labels if (phrase := phrase_in(phrases, label)) is not None]
        if not hits:
            return None
        evidence.extend(Evidence(rule.origin.rule, source, label.value, phrase) for label, phrase in hits)
    if rule.effects and not rule.effects & effects:
        return None
    if rule.stops:
        if not (isinstance(action, Stop) and action.package in rule.stops):
            return None
        evidence.append(Evidence(rule.origin.rule, Source.PACKAGE, action.package, None))
    return tuple(evidence)


def require(verdict: Verdict, grant: Grant) -> None:
    """Raise COMMIT_REFUSED (effects not granted, listed with evidence) or DENIED (rule id,
    reason, file). The message tells the agent to grant only what its user asked for."""
    if grant.allows(verdict):
        return
    match verdict:
        case Denied():
            raise Refusal(
                ErrorCode.DENIED,
                f"Rule {verdict.rule} denies this input: {verdict.reason} No --commit opens it.",
                {"rule": verdict.rule, "source": verdict.source, "evidence": evidence_data(verdict.evidence)},
            )
        case Commits():
            missing = sorted(effect.value for effect in verdict.effects - grant.effects)
            said = sorted({e.label for e in verdict.evidence if e.label is not None})
            labels = f" ({', '.join(repr(label) for label in said)})" if said else ""
            raise Refusal(
                ErrorCode.COMMIT_REFUSED,
                f"This input would {' and '.join(missing)}{labels}. It is sent only with "
                f"{' '.join(f'--commit {effect}' for effect in missing)}. "
                "Grant it only when your user asked for this commit.",
                {
                    "effects": sorted(effect.value for effect in verdict.effects),
                    "granted": sorted(effect.value for effect in grant.effects),
                    "evidence": evidence_data(verdict.evidence),
                },
            )


def evidence_data(evidence: Sequence[Evidence]) -> list[dict[str, object]]:
    return [{"rule": e.rule, "source": e.source.value, "label": e.label} for e in evidence]
