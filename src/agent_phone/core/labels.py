"""What an element says: its label surface, its display name, its stable name, and their words.

Label ownership decides which strings belong to an element. It is read two ways, and they differ
in one case: a node that is checkable and not clickable.

- The gate reads `surface_of`. The policy engine judges the words of the node that receives the
  touch, so ownership stops at a node that takes the touch (`role.takes_touch`), the predicate
  the hit plan uses. A switch that is not clickable passes the touch to its row, so its words
  belong to the row.
- The snapshot reads `display_name` and `display_detail`. Ownership stops at any touch consumer
  (`role.consumes_touch`), because a checkable node prints a line of its own.

Both read the same label fields, so the gate judges the words the agent sees, plus the
resource-ids and class names the agent does not see. A clickable `Button` with empty text owns
the words of the plain `ViewGroup` inside it. A child `Button` inside a clickable row owns its own
words, not the row.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import Enum

from agent_phone.core.role import VALUE_ROLES, Role, consumes_touch, role_of, shows_surface, takes_touch
from agent_phone.core.screen import Attrs, Flag, Node, NodeId, Screen


class LabelField(Enum):
    TEXT = "text"
    CONTENT_DESC = "content_desc"
    HINT = "hint"
    RESOURCE_ID = "resource_id"
    CLASS_NAME = "class_name"


LABEL_FIELDS: tuple[str, ...] = tuple(f.value for f in LabelField)
NON_LABEL_FIELDS: tuple[str, ...] = ("package",)
"""`tests/test_labels.py` asserts LABEL_FIELDS + NON_LABEL_FIELDS == every `str` field of
`Attrs`. A new attribute cannot reach the engine unread: the test fails until someone files it
on one side, and that is how "target a different attribute" stays closed."""

NAMING_FIELDS = frozenset({LabelField.TEXT, LabelField.CONTENT_DESC, LabelField.HINT})


@dataclass(frozen=True, slots=True)
class Label:
    """One string from one field of one node, with the provenance policy rules can filter on."""

    value: str
    field: LabelField
    node: NodeId
    node_resource_id: str

    @property
    def naming(self) -> bool:
        return self.field in NAMING_FIELDS


@dataclass(frozen=True, slots=True)
class Surface:
    owner: NodeId
    labels: tuple[Label, ...]

    @property
    def named(self) -> bool:
        """False for an icon with no text, description, hint or id: the engine calls it unlabeled.
        Class names never make a node named."""
        return any(lbl.naming or lbl.field is LabelField.RESOURCE_ID for lbl in self.labels)


ROLE_WORDS = frozenset({"button", "switch", "checkbox", "check box", "toggle button", "radio button", "tab"})
"""Trailing parts that system UIs append to a comma-joined description."""

CAMEL_HUMP = re.compile(r"(?<=[^\W_A-Z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
"""A hump follows any letter or digit that is not an upper-case ASCII letter, so a non-ASCII
lower-case letter splits too: `ModalitàAereo` -> Modalità Aereo."""
WORD = re.compile(r"[^\W_]+")


def owned(screen: Screen, node: Node, stops: Callable[[Attrs], bool] = takes_touch) -> list[Node]:
    """The node and every descendant that is not inside a nested node for which `stops` holds."""
    members: list[Node] = []
    i = node.id
    while i < node.end:
        member = screen.nodes[i]
        if member.id != node.id and stops(member.attrs):
            i = member.end
            continue
        members.append(member)
        i += 1
    return members


def surface_of(screen: Screen, node: Node) -> Surface:
    """What a touch on `node` acts on, for the gate: the labels of the node and of the descendants
    that do not take a touch themselves."""
    return Surface(node.id, tuple(label for member in owned(screen, node) for label in own_labels(member)))


def own_labels(node: Node) -> tuple[Label, ...]:
    """One Label per non-empty label field of the node itself, in `LabelField` order."""
    attrs = node.attrs
    return tuple(
        Label(value, field, node.id, attrs.resource_id)
        for field in LabelField
        if (value := getattr(attrs, field.value))
    )


def display_name(screen: Screen, node: Node, role: Role) -> str:
    """The name a snapshot line shows and a `Query` matches.

    Own text, then own content-desc, then hint for fields, then, for a touch consumer, the
    first naming label of the surface. Collections and plain views name themselves from their
    own fields only (`role.shows_surface`). A field's typed text is its value, not its name.
    Some system UIs write a description as comma-joined parts ending in the role word
    ("<name>,<state>,Button"): commas become spaces and a trailing role word is dropped.
    """
    shown = shown_values(screen, node, role)
    return shown[0] if shown else ""


def display_detail(screen: Screen, node: Node) -> str:
    """The values the line shows after its name, joined, for the snapshot line's second string."""
    return ", ".join(shown_values(screen, node, role_of(node.attrs))[1:])


def stable_name(screen: Screen, node: Node, role: Role) -> str | None:
    """The part of the name that identifies the element, or None.

    Mutable values never identify: a field's typed text, a slider's value, a checkbox's
    checked state, a text that the surface marks as a password. A field keeps its hint and
    content-desc, so its identity survives text being typed into it. The display name already
    leaves every one of these out, so the stable name is the display name when there is one.
    """
    return display_name(screen, node, role) or None


def shown_values(screen: Screen, node: Node, role: Role) -> tuple[str, ...]:
    """The naming values a snapshot line shows for the node, in name order, cleaned and
    without repeats. The first is the name, the rest are the detail."""
    labels = tuple(label for member in shown_nodes(screen, node, role) for label in own_labels(member))
    return naming_values(screen, labels)


def shown_nodes(screen: Screen, node: Node, role: Role) -> list[Node]:
    """The nodes whose labels `shown_values` reads: the node's surface when it shows one."""
    return owned(screen, node, consumes_touch) if shows_surface(node.attrs, role) else [node]


def naming_values(screen: Screen, labels: Sequence[Label]) -> tuple[str, ...]:
    """The cleaned naming values of `labels`, in order, without repeats and without values
    the user changes or must not see."""
    shown: list[str] = []
    for label in labels:
        if label.naming and not is_value(screen, label):
            value = cleaned(label)
            if value and value not in shown:
                shown.append(value)
    return tuple(shown)


def typed_text(node: Node) -> str | None:
    """The text a field or slider holds, which may be empty. None for every other node, and for
    a secret field, whose text nothing reads: not a snapshot, a query or `get`."""
    attrs = node.attrs
    if role_of(attrs) in VALUE_ROLES and Flag.PASSWORD not in attrs.flags:
        return attrs.text
    return None


def is_value(screen: Screen, label: Label) -> bool:
    """True for text the user changes or must not see: a field's or slider's own text, and
    any text of a password node."""
    source = screen.node(label.node).attrs
    return label.field is LabelField.TEXT and (
        role_of(source) in VALUE_ROLES or Flag.PASSWORD in source.flags
    )


def cleaned(label: Label) -> str:
    value = label.value
    if label.field is LabelField.CONTENT_DESC:
        parts = [part.strip() for part in value.split(",")]
        if len(parts) > 1 and parts[-1].casefold() in ROLE_WORDS:
            value = " ".join(parts[:-1])
    return " ".join(value.split())


def words(value: str, field: LabelField) -> tuple[str, ...]:
    """Lower-case word tokens for phrase matching.

    NFKC + casefold, then split on anything that is not a letter or digit, on camelCase humps
    and on `_`. A resource-id contributes only its entry name (`row_feed_button_share` ->
    row feed button share), a class only its simple name (`ShareButton` -> share button).
    """
    if field is LabelField.RESOURCE_ID:
        value = value.rpartition("/")[2]
    elif field is LabelField.CLASS_NAME:
        value = value.rpartition(".")[2]
    value = CAMEL_HUMP.sub(" ", unicodedata.normalize("NFKC", value))
    return tuple(WORD.findall(value.casefold()))


def normalized(value: str) -> str:
    """Whitespace-collapsed casefold of a whole label, for exact-label policy rules."""
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())
