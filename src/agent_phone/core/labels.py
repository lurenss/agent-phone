"""What an element says: its label surface, its display name, its stable name, and their words.

One function, `surface_of`, decides which strings belong to an element. The snapshot's name,
the ref fingerprint and the policy engine all read from it, so the gate judges the same words
the agent sees, plus the resource-ids and class names the agent does not see.

The surface of a node is its own label fields plus those of every descendant that is not inside
a nested touch consumer. A clickable `Button` with empty text owns the words of the plain
`ViewGroup` inside it. A child `Button` inside a clickable row owns its own words, not the row.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from agent_phone.core.role import Role
from agent_phone.core.screen import Node, NodeId, Screen


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


def surface_of(screen: Screen, node: Node) -> Surface:
    # TODO: walk screen.subtree(node.id); skip the subtree of any descendant d != node with
    # consumes_touch(d.attrs); for each kept node emit one Label per non-empty label field.
    # A resource-id label holds the full id; `words` reads only its entry name.
    raise NotImplementedError


def display_name(screen: Screen, node: Node, role: Role) -> str:
    """The name a snapshot line shows and a `Query` matches.

    Own text, then own content-desc, then hint for fields, then the first naming label of the
    surface. Collections name themselves from their own fields only, never from a row. A
    field's typed text is its value, not its name. Some system UIs write a description as
    comma-joined parts ending in the role word ("<name>,<state>,Button"): commas become spaces
    and a trailing role word is dropped.
    """
    raise NotImplementedError


def display_detail(screen: Screen, node: Node) -> str:
    """The surface's other naming labels, joined, for the snapshot line's second string."""
    raise NotImplementedError


def stable_name(screen: Screen, node: Node, role: Role) -> str | None:
    """The part of the name that identifies the element, or None.

    Mutable values never identify: a field's typed text, a slider's value, a checkbox's
    checked state, a text that the surface marks as a password. A field keeps its hint and
    content-desc, so its identity survives text being typed into it.
    """
    raise NotImplementedError


def words(value: str, field: LabelField) -> tuple[str, ...]:
    """Lower-case word tokens for phrase matching.

    NFKC + casefold, then split on anything that is not a letter or digit, on camelCase humps
    and on `_`. A resource-id contributes only its entry name (`row_feed_button_share` ->
    row feed button share), a class only its simple name (`ShareButton` -> share button).
    """
    raise NotImplementedError


def normalized(value: str) -> str:
    """Whitespace-collapsed casefold of a whole label, for exact-label policy rules."""
    raise NotImplementedError
