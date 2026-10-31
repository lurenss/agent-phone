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
from typing import NewType

from agent_phone.core.device import DeviceProfile, Package
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
        raise NotImplementedError


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
        raise NotImplementedError


def parse_policy(doc: Mapping[str, object], source: str) -> tuple[Policy, frozenset[RuleId]]:
    """Validate one parsed TOML document. Returns its rules and the ids it disables.

    Raises `Refusal(POLICY_INVALID)` naming the file, the table and the field: an unknown key,
    an unknown effect or window kind, an empty `words`, a duplicate id. Words are tokenized
    here with `labels.words`, so rules and labels split text the same way.
    """
    raise NotImplementedError


def merge(layers: tuple[tuple[Policy, frozenset[RuleId]], ...]) -> Policy:
    """Apply layers in order. Disabling a profile deny rule raises `Refusal(POLICY_INVALID)`."""
    raise NotImplementedError


def protect_rules(profile: DeviceProfile) -> tuple[DenyRule, ...]:
    # TODO: per ProtectedPackage p, two rules with from_profile=True:
    #   stops={p.package}                                       -> refuses `stop p`
    #   effects={DELETE, SYSTEM}, context_words=p.labels words  -> refuses "Force stop",
    #                                                              "Uninstall", "Clear data"
    #                                                              on p's App info screen
    raise NotImplementedError
