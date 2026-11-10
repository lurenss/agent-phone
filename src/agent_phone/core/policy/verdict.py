"""What the policy engine is given and what it answers: the `Site` of an input, the `Verdict`
on it with its evidence, and the `Grant` the caller gave. `engine.classify` builds a verdict and
`engine.require` holds it against a grant.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from agent_phone.core.device import Package
from agent_phone.core.labels import Label, Surface
from agent_phone.core.policy.model import Effect, Phrase, RuleId
from agent_phone.core.screen import WindowKind


@dataclass(frozen=True, slots=True)
class Site:
    """`receiver` is None when no element of the screen receives the input: a launch, a stop, a
    link, a rotation, the clipboard, back, home and recents, and Enter with nothing in focus.

    `context` is the rest of the receiver's window. The receiver's own labels are not repeated
    in it. For Enter with nothing in focus it is every label of the active window.
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
