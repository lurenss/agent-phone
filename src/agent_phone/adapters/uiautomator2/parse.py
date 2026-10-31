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

import re
import xml.etree.ElementTree as ET

from agent_phone.core.device import Package
from agent_phone.core.geometry import Rect, Rotation, Size
from agent_phone.core.outcome import ErrorCode, Refusal
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


EDITABLE_CLASSES = frozenset({"EditText", "AutoCompleteTextView"})
"""The dump has no `editable` attribute, so these class simple names stand in for it."""

BOUNDS = re.compile(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]")


def parse_hierarchy(xml: str, natural_display: Size, ime_package: Package | None) -> Screen:
    """Raise `Refusal(TRANSPORT)` on XML that does not parse, `Refusal(NO_SURFACE)` on an
    empty hierarchy (screen off). `natural_display` is swapped for rotation 1 and 3, as the
    landscape fixtures (`settings-home.xml`, `notification-shade.xml`) need."""
    try:
        hierarchy = ET.fromstring(xml)
    except ET.ParseError as error:
        raise Refusal(ErrorCode.TRANSPORT, f"The screen dump is not valid XML: {error}.") from error
    try:
        rotation = Rotation(int(hierarchy.get("rotation", "0")))
    except ValueError as error:
        raise Refusal(
            ErrorCode.TRANSPORT, f"The screen dump has rotation {hierarchy.get('rotation')!r}."
        ) from error
    roots = hierarchy.findall("node")
    if not roots:
        raise Refusal(ErrorCode.NO_SURFACE, "The screen dump has no window. The screen may be off.")
    display = natural_display
    if rotation in (Rotation.LEFT, Rotation.RIGHT):
        display = Size(natural_display.height, natural_display.width)
    windows = [window_spec(parse_node(root), order, ime_package) for order, root in enumerate(roots)]
    return Screen.build(display, rotation, windows)


def parse_node(element: ET.Element) -> NodeSpec:
    return NodeSpec(
        parse_attrs(element.attrib), tuple(parse_node(child) for child in element.findall("node"))
    )


def parse_bounds(text: str) -> Rect:
    """`[0,63][1080,1920]` -> Rect(0, 63, 1080, 1920)."""
    match = BOUNDS.fullmatch(text)
    if match is None:
        raise Refusal(ErrorCode.TRANSPORT, f"The screen dump has bounds {text!r}.")
    left, top, right, bottom = (int(group) for group in match.groups())
    return Rect(left, top, right, bottom)


def parse_attrs(attrib: dict[str, str]) -> Attrs:
    class_name = attrib.get("class", "")
    flags = {flag for name, flag in BOOL_FLAGS.items() if attrib.get(name) == "true"}
    if class_name.rpartition(".")[2] in EDITABLE_CLASSES:
        flags.add(Flag.EDITABLE)
    drawing_order = attrib.get("drawing-order")
    if drawing_order is not None and not drawing_order.lstrip("-").isdigit():
        raise Refusal(ErrorCode.TRANSPORT, f"The screen dump has drawing-order {drawing_order!r}.")
    return Attrs(
        class_name=class_name,
        package=attrib.get("package", ""),
        resource_id=attrib.get("resource-id", ""),
        text=attrib.get("text", ""),
        content_desc=attrib.get("content-desc", ""),
        hint=attrib.get("hint", ""),
        bounds=parse_bounds(attrib.get("bounds", "")),
        flags=frozenset(flags),
        drawing_order=int(drawing_order) if drawing_order is not None else None,
        native_id=None,
    )


def window_spec(root: NodeSpec, order: int, ime_package: Package | None) -> WindowSpec:
    package = Package(root.attrs.package)
    if ime_package is not None and package == ime_package:
        kind = WindowKind.INPUT_METHOD
    elif package in PLATFORM_UI:
        kind = WindowKind.SYSTEM
    else:
        kind = WindowKind.APPLICATION
    return WindowSpec(package, kind, root.attrs.bounds, active=order == 0, layer=None, root=root)
