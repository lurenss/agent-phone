"""The policy rule schema: what a rule may contain, as frozen types.

Five rule kinds, one table each in TOML (`rules.parse_policy` reads them, `rules.merge` layers
them):

- `commit`: words, keys or URI schemes that make an input carry an `Effect`.
- `exempt`: exact labels known to navigate, removed before commit words are read.
- `ignore`: labels from nodes with these resource-ids are descriptive and not read.
- `inherit`: a receiver whose name is one of these words ("OK", "Yes") takes the effects of
  its context, so "OK" under "Delete this post?" deletes.
- `deny`: refused whatever the caller grants.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import NewType

from agent_phone.core.device import Package
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
    it gets LOCALE_UNSUPPORTED for every labeled input: the engine cannot read that screen.

    `withdrawn` holds the commit rules a later layer disabled. They commit nothing, but deny
    rules still read the effects they name, so disabling `default.system` cannot switch off a
    profile's protection that denies system taps on a protected package's screen."""

    languages: frozenset[str]
    rules: tuple[Rule, ...]
    withdrawn: tuple[CommitRule, ...] = ()

    def of_kind[R: Rule](self, kind: type[R]) -> tuple[R, ...]:
        return tuple(rule for rule in self.rules if isinstance(rule, kind))
