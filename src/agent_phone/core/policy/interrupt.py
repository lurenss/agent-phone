"""Pop-ups the agent did not ask for, recognised from `[[interruption]]` rules.

An interruption is a window in which every phrase of one rule shows: a dialog that says an app is
not responding, a permission prompt, a purchase sheet, or a consumer's own "Rate us" sheet from
that consumer's policy file. Every recorded snapshot names the ones on screen
(`snapshot/capture.py`).

agent-phone never answers one. `dismiss` is the button a rule calls the safe way out, for the
caller to click through the gate like any other button.
"""

from __future__ import annotations

from dataclasses import dataclass

from agent_phone.core.labels import cleaned, is_value, own_labels, surface_of, words
from agent_phone.core.policy.engine import language_of, phrase_in
from agent_phone.core.policy.model import InterruptionKind, InterruptionRule, Phrase, Policy, RuleId
from agent_phone.core.role import takes_touch
from agent_phone.core.screen import Flag, NodeId, Screen, Window, WindowId


@dataclass(frozen=True, slots=True)
class Interruption:
    """`dismiss` is None when the window shows no button with one of the rule's `dismiss` names,
    or shows several with the first name found: the way out is never a guess."""

    rule: RuleId
    kind: InterruptionKind
    window: WindowId
    dismiss: NodeId | None
    needs_human: bool


def interruptions_of(policy: Policy, screen: Screen, locale: str) -> tuple[Interruption, ...]:
    """Pure. One entry per window and rule that matches it, in window order, then rule order. Words
    are read where the user reads them: text, content-desc and hint, never typed or secret text."""
    language = language_of(locale)
    rules = policy.of_kind(InterruptionRule)
    found = []
    for window in screen.windows if rules else ():
        labels = [
            label
            for node in screen.subtree(window.root)
            for label in own_labels(node)
            if label.naming and not is_value(screen, label)
        ]
        for rule in rules:
            if rule.scope.applies(window.package, window.kind, language) and all(
                any(phrase_in((phrase,), label) for label in labels) for phrase in rule.words
            ):
                way_out = dismiss_of(screen, window, rule.dismiss)
                found.append(Interruption(rule.origin.rule, rule.kind, window.id, way_out, rule.needs_human))
    return tuple(found)


def dismiss_of(screen: Screen, window: Window, names: tuple[Phrase, ...]) -> NodeId | None:
    """The one visible, enabled node of `window` that takes a touch and whose name is, as a whole,
    the first of `names` that any such node has. Typed text is not a name."""
    buttons = [
        (
            node.id,
            {
                words(cleaned(label), label.field)
                for label in surface_of(screen, node).labels
                if label.naming and not is_value(screen, label)
            },
        )
        for node in screen.subtree(window.root)
        if takes_touch(node.attrs) and node.has(Flag.VISIBLE) and node.has(Flag.ENABLED)
    ]
    for name in names:
        named = [node for node, said in buttons if name.words in said]
        if named:
            return named[0] if len(named) == 1 else None
    return None
