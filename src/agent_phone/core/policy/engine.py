"""The policy engine: what an input would do, judged from what it would land on.

The engine never sees how the caller named the target. It is given the `Site` that act()
derived from the live screen: the node that will receive the touch at the planned point
(`act/hit.py`), that node's whole label surface (every label field of it and of the
descendants it owns, `labels.surface_of`), and the context around it. A ref, a query by text,
a query by resource-id and a raw point that land on the same node get the same verdict. That
is the property the commit table tests: each commit phrase is planted in text, in
content-desc, in hint, in a resource-id, in a class name and in a child's text, and every
placement must give the same verdict.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from agent_phone.core.device import Package
from agent_phone.core.labels import Label, Surface
from agent_phone.core.outcome import ErrorCode, Refusal
from agent_phone.core.phone import InputAction
from agent_phone.core.policy.rules import Effect, Phrase, Policy, RuleId
from agent_phone.core.screen import WindowKind


@dataclass(frozen=True, slots=True)
class Site:
    """`receiver` is None when no touch consumer is under the point (a blank area).

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


def classify(policy: Policy, action: InputAction, site: Site | None, language: str) -> Verdict:
    """Pure. `site` is None for inputs that land on no node (keys, launch, stop, rotation...).

    Raises `Refusal(LOCALE_UNSUPPORTED)` when a labeled input arrives and `language` is not in
    `policy.languages`.
    """
    # TODO:
    #   Tap | LongPress | Activate:
    #     receiver None                      -> Clear(NO_RECEIVER)
    #     drop labels whose node_resource_id an applicable IgnoreRule names
    #     drop labels whose normalized value an applicable ExemptRule lists (remember the ids)
    #     not receiver.named                 -> Effect.UNLABELED, Source.UNLABELED
    #     commit phrases in the remaining labels' words -> effects, Source.RECEIVER
    #     no effects and the receiver's naming labels match an InheritRule
    #                                        -> commit phrases in context -> Source.CONTEXT
    #   Key: CommitRule.keys; OpenUri: CommitRule.uri_schemes on the scheme; SetText, Swipe,
    #     Launch, Rotate, SetPower, SetClipboard: no commit rules apply
    #   then every applicable DenyRule; the first that matches -> Denied
    #   effects -> Commits, else Clear(EXEMPT if an exemption removed a phrase else NO_COMMIT_WORDS)
    raise NotImplementedError


def require(verdict: Verdict, grant: Grant) -> None:
    """Raise COMMIT_REFUSED (effects not granted, listed with evidence) or DENIED (rule id,
    reason, file). The message tells the agent to grant only what its user asked for."""
    if grant.allows(verdict):
        return
    code = ErrorCode.DENIED if isinstance(verdict, Denied) else ErrorCode.COMMIT_REFUSED
    raise Refusal(code, "TODO: message from verdict and grant")
