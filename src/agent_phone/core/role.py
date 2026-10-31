"""The closed role vocabulary, and the one place that maps Android classes and flags onto it.

Compose and WebView content arrives as bare `android.view.View`, so role comes from flags
first and class second: a clickable View is a button whatever its class says.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import Enum

from agent_phone.core.screen import Attrs, Flag


class Role(Enum):
    BUTTON = "button"
    TEXT_FIELD = "field"
    CHECKBOX = "checkbox"
    SWITCH = "switch"
    RADIO = "radio"
    TAB = "tab"
    SLIDER = "slider"
    DROPDOWN = "dropdown"
    LIST = "list"
    PAGER = "pager"
    SCROLL = "scroll"
    WEB = "web"
    IMAGE = "image"
    TEXT = "text"
    PROGRESS = "progress"
    GROUP = "group"


CLASS_ROLES: Mapping[str, Role] = {
    "Button": Role.BUTTON,
    "ImageButton": Role.BUTTON,
    "EditText": Role.TEXT_FIELD,
    "AutoCompleteTextView": Role.TEXT_FIELD,
    "CheckBox": Role.CHECKBOX,
    "Switch": Role.SWITCH,
    "SwitchCompat": Role.SWITCH,
    "ToggleButton": Role.SWITCH,
    "RadioButton": Role.RADIO,
    "SeekBar": Role.SLIDER,
    "Spinner": Role.DROPDOWN,
    "RecyclerView": Role.LIST,
    "ListView": Role.LIST,
    "GridView": Role.LIST,
    "ViewPager": Role.PAGER,
    "ScrollView": Role.SCROLL,
    "HorizontalScrollView": Role.SCROLL,
    "NestedScrollView": Role.SCROLL,
    "WebView": Role.WEB,
    "ImageView": Role.IMAGE,
    "TextView": Role.TEXT,
    "ProgressBar": Role.PROGRESS,
}
"""Keyed by the class's simple name, so `androidx.recyclerview.widget.RecyclerView` and
`android.support.v7.widget.RecyclerView` (both in the fixtures) map the same way."""

COLLECTIONS = frozenset({Role.LIST, Role.PAGER, Role.SCROLL})


def role_of(attrs: Attrs) -> Role:
    # TODO:
    #   base = CLASS_ROLES.get(simple_name(attrs.class_name), Role.GROUP)
    #   EDITABLE flag -> TEXT_FIELD whatever the class (Compose text fields are Views)
    #   CHECKABLE and base not in {CHECKBOX, SWITCH, RADIO} -> CHECKBOX
    #   base in {GROUP, IMAGE, TEXT} and consumes_touch(attrs) -> BUTTON
    #   base is GROUP and SCROLLABLE -> SCROLL
    raise NotImplementedError


def consumes_touch(attrs: Attrs) -> bool:
    """True when Android would hand a tap to this node rather than pass it to its parent."""
    return bool(attrs.flags & {Flag.CLICKABLE, Flag.LONG_CLICKABLE, Flag.CHECKABLE})


def is_actionable(attrs: Attrs, role: Role) -> bool:
    """Gets a ref in a snapshot. Disabled nodes still get one, so `wait` and `is` can name them."""
    # TODO: VISIBLE and (consumes_touch or SCROLLABLE or role is TEXT_FIELD or role is SLIDER)
    raise NotImplementedError
