"""uiautomator2's `dumpWindowHierarchy` XML into core `WindowSpec`s. XML never leaves this module.

The server dump has one `<node>` per window under `<hierarchy rotation="N">` and no window
type, layer or focus attribute. What this module infers, and from what:

- active: the first window. The server lists `getRootInActiveWindow()` first and then the rest
  of `getWindows()` (androidx UiDevice.getWindowRoots). Matches all four fixtures; not yet
  probed with a dialog over an app. Open question for unit 3.
- kind: INPUT_METHOD for the device's default IME package (`shell.py` reads it), SYSTEM for
  the platform's own UI packages in PLATFORM_UI, APPLICATION otherwise. A backend that reads
  AccessibilityWindowInfo replaces all of this with facts.
- layer: None. The engine therefore treats every non-active window over a point as covering
  it, except a full-screen application window (`core/act/hit.py`).
"""

from __future__ import annotations

from agent_phone.core.device import Package
from agent_phone.core.geometry import Rect, Rotation, Size
from agent_phone.core.screen import Attrs, Flag, NodeSpec, Screen, WindowKind, WindowSpec

PLATFORM_UI: frozenset[str] = frozenset({"android", "com.android.systemui"})
"""Android's own window owners, not apps. The one place a package name appears in this
backend, because the dump gives no window type to read instead."""

BOOL_FLAGS: dict[str, Flag] = {
    "clickable": Flag.CLICKABLE,
    "long-clickable": Flag.LONG_CLICKABLE,
    "scrollable": Flag.SCROLLABLE,
    "checkable": Flag.CHECKABLE,
    "checked": Flag.CHECKED,
    "enabled": Flag.ENABLED,
    "focusable": Flag.FOCUSABLE,
    "focused": Flag.FOCUSED,
    "selected": Flag.SELECTED,
    "password": Flag.PASSWORD,
    "visible-to-user": Flag.VISIBLE,
}


def parse_hierarchy(xml: str, natural_display: Size, ime_package: Package | None) -> Screen:
    """Raise `Refusal(TRANSPORT)` on XML that does not parse, `Refusal(NO_SURFACE)` on an
    empty hierarchy (screen off). `natural_display` is swapped for rotation 1 and 3, as the
    landscape fixtures (`settings-home.xml`, `notification-shade.xml`) need."""
    raise NotImplementedError


def parse_bounds(text: str) -> Rect:
    """`[0,63][1080,1920]` -> Rect(0, 63, 1080, 1920)."""
    raise NotImplementedError


def parse_attrs(attrib: dict[str, str]) -> Attrs:
    # TODO: EDITABLE when class simple name is EditText or AutoCompleteTextView, because the
    # dump has no `editable` attribute; drawing_order None when absent; hint "" when absent (API < 26).
    raise NotImplementedError


def window_spec(root: NodeSpec, order: int, ime_package: Package | None) -> WindowSpec:
    _ = (Rotation, WindowKind)
    raise NotImplementedError
