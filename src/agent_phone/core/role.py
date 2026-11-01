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
SELF_NAMED = COLLECTIONS | {Role.WEB}
"""Roles that name themselves from their own fields only. A list's rows and a page's content
print their own lines instead of becoming the container's words."""
VALUE_ROLES = frozenset({Role.TEXT_FIELD, Role.SLIDER})
"""Roles whose own text is a value the user changes, shown as `value=` and never as a name."""
CHOICES = frozenset({Role.CHECKBOX, Role.SWITCH, Role.RADIO})


def simple_name(class_name: str) -> str:
    return class_name.rpartition(".")[2]


def role_of(attrs: Attrs) -> Role:
    base = CLASS_ROLES.get(simple_name(attrs.class_name), Role.GROUP)
    if Flag.EDITABLE in attrs.flags:
        return Role.TEXT_FIELD
    if Flag.CHECKABLE in attrs.flags and base not in CHOICES:
        return Role.CHECKBOX
    if base in (Role.GROUP, Role.IMAGE, Role.TEXT) and consumes_touch(attrs):
        return Role.BUTTON
    if base is Role.GROUP and Flag.SCROLLABLE in attrs.flags:
        return Role.SCROLL
    return base


def consumes_touch(attrs: Attrs) -> bool:
    """True when Android would hand a tap to this node rather than pass it to its parent."""
    return bool(attrs.flags & {Flag.CLICKABLE, Flag.LONG_CLICKABLE, Flag.CHECKABLE})


def takes_touch(attrs: Attrs) -> bool:
    """True when Android hands a touch to this node: `View.onTouchEvent` keeps a touch only for a
    clickable or long-clickable view. A checkable view that is not clickable, such as the switch
    of a preference row, passes the touch to its row. The hit plan and the gate's label ownership
    use this. `consumes_touch`, which also counts a checkable node, decides refs, roles and the
    names a snapshot prints."""
    return bool(attrs.flags & {Flag.CLICKABLE, Flag.LONG_CLICKABLE})


def is_actionable(attrs: Attrs, role: Role) -> bool:
    """Gets a ref in a snapshot. Disabled nodes still get one, so `wait` and `is` can name them."""
    return Flag.VISIBLE in attrs.flags and (
        consumes_touch(attrs) or Flag.SCROLLABLE in attrs.flags or role in VALUE_ROLES
    )


def shows_surface(attrs: Attrs, role: Role) -> bool:
    """True when the node's name and detail come from its whole label surface: a touch consumer
    owns the words of the plain views inside it. Every other node shows only its own fields, so
    a layout around a text never repeats that text."""
    return consumes_touch(attrs) and role not in SELF_NAMED
