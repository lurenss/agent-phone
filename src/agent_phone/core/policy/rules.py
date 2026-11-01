"""The policy rule schema. Rules are data; this module only says what a rule may contain.

Sources, merged in this order into one `Policy`:

1. `agent_phone/policy/default.toml`, shipped with the package: generic verbs per language,
   framework ids (`android:id/summary`), keys and URI schemes. It names no app.
2. The device profile's protections (`protect_rules`) and its `policy_files`.
3. Policy files the caller passes (`--policy`, or `open_phone(policies=...)`), such as
   `examples/business_suite/policy.toml`.

Later sources add rules and may `disable` an earlier rule by id. Nothing may disable a deny
rule that came from a device profile, because a consumer's file must not unprotect a phone.

Five rule kinds, one table each in TOML:

- `commit`: words, keys or URI schemes that make an input carry an `Effect`.
- `exempt`: exact labels known to navigate, removed before commit words are read.
- `ignore`: labels from nodes with these resource-ids are descriptive and not read.
- `inherit`: a receiver whose name is one of these words ("OK", "Yes") takes the effects of
  its context, so "OK" under "Delete this post?" deletes.
- `deny`: refused whatever the caller grants.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import NewType, NoReturn

from agent_phone.core.device import DeviceProfile, Package
from agent_phone.core.labels import LabelField, normalized, words
from agent_phone.core.outcome import ErrorCode, Refusal
from agent_phone.core.phone import KeyName
from agent_phone.core.screen import WindowKind

RuleId = NewType("RuleId", str)


@dataclass(frozen=True, slots=True)
class Phrase:
    """Consecutive words in one label. `anchored` (written `^post`) must start the label: on
    the four fixtures an unanchored "post" committed "More actions for this post" and
    "Create new post", and the anchor cleared both without an exemption."""

    words: tuple[str, ...]
    anchored: bool


class Effect(Enum):
    """What an input does that cannot be taken back. `--commit` grants effects, not words."""

    PUBLISH = "publish"
    SCHEDULE = "schedule"
    SEND = "send"
    DELETE = "delete"
    PURCHASE = "purchase"
    SOCIAL = "social"
    SYSTEM = "system"
    CONFIRM = "confirm"
    UNLABELED = "unlabeled"


@dataclass(frozen=True, slots=True)
class Scope:
    """Every non-empty set must contain the input's value. All empty means everywhere."""

    packages: frozenset[Package]
    window_kinds: frozenset[WindowKind]
    languages: frozenset[str]

    def applies(self, package: Package, kind: WindowKind, language: str) -> bool:
        return (
            (not self.packages or package in self.packages)
            and (not self.window_kinds or kind in self.window_kinds)
            and (not self.languages or language in self.languages)
        )


@dataclass(frozen=True, slots=True)
class Origin:
    rule: RuleId
    source: str
    reason: str


@dataclass(frozen=True, slots=True)
class CommitRule:
    origin: Origin
    scope: Scope
    effect: Effect
    words: tuple[Phrase, ...]
    keys: frozenset[KeyName]
    uri_schemes: frozenset[str]


@dataclass(frozen=True, slots=True)
class ExemptRule:
    origin: Origin
    scope: Scope
    labels: frozenset[str]


@dataclass(frozen=True, slots=True)
class IgnoreRule:
    origin: Origin
    scope: Scope
    node_ids: frozenset[str]


@dataclass(frozen=True, slots=True)
class InheritRule:
    origin: Origin
    scope: Scope
    words: tuple[Phrase, ...]


@dataclass(frozen=True, slots=True)
class DenyRule:
    """Matches when every non-empty condition holds.

    `words` are read in the receiver, `context_words` in its context, `effects` against the
    effects the engine already found, `stops` against the package of a `stop` command.
    """

    origin: Origin
    scope: Scope
    words: tuple[Phrase, ...]
    context_words: tuple[Phrase, ...]
    effects: frozenset[Effect]
    stops: frozenset[Package]
    from_profile: bool


Rule = CommitRule | ExemptRule | IgnoreRule | InheritRule | DenyRule


@dataclass(frozen=True, slots=True)
class Policy:
    """`languages` is the union the commit rules cover. A device whose locale language is not in
    it gets LOCALE_UNSUPPORTED for every labeled input: the engine cannot read that screen."""

    languages: frozenset[str]
    rules: tuple[Rule, ...]

    def of_kind[R: Rule](self, kind: type[R]) -> tuple[R, ...]:
        return tuple(rule for rule in self.rules if isinstance(rule, kind))


SCOPE_KEYS = frozenset({"id", "reason", "packages", "window_kinds", "languages"})
TABLE_KEYS: Mapping[str, frozenset[str]] = {
    "commit": SCOPE_KEYS | {"effect", "words", "keys", "uri_schemes"},
    "exempt": SCOPE_KEYS | {"labels"},
    "ignore": SCOPE_KEYS | {"node_ids"},
    "inherit": SCOPE_KEYS | {"words"},
    "deny": SCOPE_KEYS | {"words", "context_words", "effects", "stops"},
}
DOCUMENT_KEYS = frozenset({"languages", "disable", *TABLE_KEYS})


def parse_policy(
    doc: Mapping[str, object], source: str, from_profile: bool = False
) -> tuple[Policy, frozenset[RuleId]]:
    """Validate one parsed TOML document. Returns its rules and the ids it disables.

    Raises `Refusal(POLICY_INVALID)` naming the file, the table and the field: an unknown key,
    an unknown effect or window kind, an empty `words`, a duplicate id. Words are tokenized
    here with `labels.words`, so rules and labels split text the same way. `from_profile` marks
    the deny rules of a device profile's own tables; the profile parser strips its `[device]`
    and `[[protected]]` tables before calling this.
    """
    top = Table(source, "document", 0, doc)
    for key in doc:
        if key not in DOCUMENT_KEYS:
            top.fail(key, "is not a policy key")
    rules: list[Rule] = []
    for kind in TABLE_KEYS:
        entries = doc.get(kind, [])
        if not isinstance(entries, list) or not all(isinstance(entry, dict) for entry in entries):
            top.fail(kind, f"must be an array of tables, written [[{kind}]]")
        for n, entry in enumerate(entries):
            table = Table(source, kind, n + 1, entry)
            rule = parse_rule(table, from_profile)
            if any(earlier.origin.rule == rule.origin.rule for earlier in rules):
                table.fail("id", "is already used by another table of this file")
            rules.append(rule)
    languages = frozenset(top.texts("languages"))
    disabled = frozenset(RuleId(rule) for rule in top.texts("disable"))
    return Policy(languages, tuple(rules)), disabled


def parse_rule(table: Table, from_profile: bool) -> Rule:
    for key in table.data:
        if key not in TABLE_KEYS[table.kind]:
            table.fail(key, f"is not a key of [[{table.kind}]]")
    origin = Origin(RuleId(table.text("id")), table.source, table.text("reason"))
    scope = Scope(
        packages=frozenset(Package(p) for p in table.texts("packages")),
        window_kinds=table.choices("window_kinds", WindowKind),
        languages=frozenset(table.texts("languages")),
    )
    match table.kind:
        case "commit":
            rule = CommitRule(
                origin,
                scope,
                table.choice("effect", Effect),
                table.phrases("words"),
                table.choices("keys", KeyName),
                frozenset(table.texts("uri_schemes")),
            )
            if not (rule.words or rule.keys or rule.uri_schemes):
                table.fail("words", "is missing, and so are keys and uri_schemes: the rule matches nothing")
            return rule
        case "exempt":
            return ExemptRule(
                origin, scope, frozenset(normalized(label) for label in table.texts("labels", True))
            )
        case "ignore":
            return IgnoreRule(origin, scope, frozenset(table.texts("node_ids", True)))
        case "inherit":
            return InheritRule(origin, scope, table.phrases("words", True))
        case _:
            rule = DenyRule(
                origin,
                scope,
                table.phrases("words"),
                table.phrases("context_words"),
                table.choices("effects", Effect),
                frozenset(Package(p) for p in table.texts("stops")),
                from_profile,
            )
            if not (rule.words or rule.context_words or rule.effects or rule.stops):
                table.fail(
                    "words", "is missing, and so are context_words, effects and stops: it denies everything"
                )
            return rule


@dataclass(frozen=True, slots=True)
class Table:
    """One table of one policy file, with what an error message must name."""

    source: str
    kind: str
    number: int
    data: Mapping[str, object]

    def fail(self, field: str, problem: str) -> NoReturn:
        where = "top level" if self.kind == "document" else f"[[{self.kind}]] #{self.number}"
        rule = self.data.get("id") if self.kind != "document" else None
        named = f" (id {rule!r})" if isinstance(rule, str) else ""
        raise Refusal(
            ErrorCode.POLICY_INVALID,
            f"{self.source}: {where}{named}: {field} {problem}.",
            {"source": self.source, "table": self.kind, "field": field},
        )

    def text(self, field: str) -> str:
        value = self.data.get(field)
        if not isinstance(value, str) or not value.strip():
            self.fail(field, "must be a non-empty string")
        return value

    def texts(self, field: str, required: bool = False) -> tuple[str, ...]:
        if field not in self.data:
            if required:
                self.fail(field, "is missing")
            return ()
        value = self.data[field]
        if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value):
            self.fail(field, "must be a list of non-empty strings")
        if not value:
            self.fail(field, "is empty")
        return tuple(value)

    def phrases(self, field: str, required: bool = False) -> tuple[Phrase, ...]:
        found = []
        for text in self.texts(field, required):
            tokens = words(text.removeprefix("^"), LabelField.TEXT)
            if not tokens:
                self.fail(field, f"holds {text!r}, which has no words")
            found.append(Phrase(tokens, anchored=text.startswith("^")))
        return tuple(found)

    def choice[E: Enum](self, field: str, enum: type[E]) -> E:
        value = self.text(field)
        try:
            return enum(value)
        except ValueError:
            allowed = ", ".join(member.value for member in enum)
            self.fail(field, f"is {value!r}, not one of {allowed}")

    def choices[E: Enum](self, field: str, enum: type[E]) -> frozenset[E]:
        found = set()
        for value in self.texts(field):
            try:
                found.add(enum(value))
            except ValueError:
                allowed = ", ".join(member.value for member in enum)
                self.fail(field, f"holds {value!r}, not one of {allowed}")
        return frozenset(found)


def merge(layers: tuple[tuple[Policy, frozenset[RuleId]], ...]) -> Policy:
    """Apply layers in order. Disabling a profile deny rule raises `Refusal(POLICY_INVALID)`.

    A layer may disable only rules an earlier layer defined, and may not reuse an id that is
    still in force: a disable that matches nothing is a mistake in that file.
    """
    rules: list[Rule] = []
    languages: set[str] = set()
    for policy, disabled in layers:
        defined = {rule.origin.rule: rule for rule in rules}
        for rule_id in sorted(disabled):
            target = defined.get(rule_id)
            if target is None:
                raise Refusal(
                    ErrorCode.POLICY_INVALID,
                    f"A policy file disables {rule_id!r}, which no earlier policy defines.",
                    {"rule": rule_id},
                )
            if isinstance(target, DenyRule) and target.from_profile:
                raise Refusal(
                    ErrorCode.POLICY_INVALID,
                    f"A policy file disables {rule_id!r}, a deny rule of the device profile "
                    f"{target.origin.source}. No policy file can unprotect a device.",
                    {"rule": rule_id, "source": target.origin.source},
                )
        rules = [rule for rule in rules if rule.origin.rule not in disabled]
        in_force = {rule.origin.rule: rule.origin.source for rule in rules}
        for rule in policy.rules:
            if rule.origin.rule in in_force:
                raise Refusal(
                    ErrorCode.POLICY_INVALID,
                    f"Rule id {rule.origin.rule!r} is defined in {in_force[rule.origin.rule]} and again in "
                    f"{rule.origin.source}. Disable the first to replace it.",
                    {"rule": rule.origin.rule, "source": rule.origin.source},
                )
        rules.extend(policy.rules)
        languages |= policy.languages
    return Policy(frozenset(languages), tuple(rules))


def protect_rules(profile: DeviceProfile, source: str) -> tuple[DenyRule, ...]:
    """Two deny rules per protected package, both marked as the profile's own:

    - `profile.protect.<package>.stop` refuses `stop <package>`;
    - `profile.protect.<package>.app-info` refuses a tap that would delete or change system
      state (Force stop, Uninstall, Clear data, Disable) on a screen that names the package or
      one of its labels, such as its App info page.
    """
    everywhere = Scope(frozenset(), frozenset(), frozenset())
    rules = []
    for protected in profile.protected:
        names = tuple(
            Phrase(tokens, anchored=False)
            for name in (*protected.labels, protected.package)
            if (tokens := words(name, LabelField.TEXT))
        )
        stem = f"profile.protect.{protected.package}"
        rules.append(
            DenyRule(
                Origin(RuleId(f"{stem}.stop"), source, protected.reason),
                everywhere,
                (),
                (),
                frozenset(),
                frozenset({protected.package}),
                from_profile=True,
            )
        )
        rules.append(
            DenyRule(
                Origin(RuleId(f"{stem}.app-info"), source, protected.reason),
                everywhere,
                (),
                names,
                frozenset({Effect.DELETE, Effect.SYSTEM}),
                frozenset(),
                from_profile=True,
            )
        )
    return tuple(rules)
