"""uiautomator2's `dumpWindowHierarchy` XML into core `WindowSpec`s. XML never leaves this module.

The server dump has one `<node>` per window under `<hierarchy rotation="N">` and no window
type, layer or focus attribute. What this module infers, and from what:

- active: the first window that is neither a status or navigation strip nor the keyboard. The
  server lists `getRootInActiveWindow()` first and then the rest of `getWindows()` (androidx
  UiDevice.getWindowRoots), so while it knows an active window the first one is it (A2-7). A server
  that started after the screen last changed knows none, and lists every window by layer, top
  first, so the status bar comes first and the app second, for as long as nothing changes (A2-8).
  Skipping the strip and the keyboard finds the app in both orders. A dump of only strips has no
  active window.
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

STRIP_FRACTION = 0.08
"""The most a status or navigation bar takes of the display across its thin side. The J7's status
bar takes 3.3%, and a three-button navigation bar is about 7.5%."""

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
    nodes = [parse_node(root) for root in roots]
    kinds = [window_kind(node.attrs, ime_package) for node in nodes]
    active = next(
        (
            i
            for i, (node, kind) in enumerate(zip(nodes, kinds, strict=True))
            if could_hold_focus(node, kind, display)
        ),
        None,
    )
    windows = [
        WindowSpec(Package(node.attrs.package), kind, node.attrs.bounds, i == active, None, node)
        for i, (node, kind) in enumerate(zip(nodes, kinds, strict=True))
    ]
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


def window_kind(attrs: Attrs, ime_package: Package | None) -> WindowKind:
    package = Package(attrs.package)
    if ime_package is not None and package == ime_package:
        return WindowKind.INPUT_METHOD
    if package in PLATFORM_UI:
        return WindowKind.SYSTEM
    return WindowKind.APPLICATION


def could_hold_focus(root: NodeSpec, kind: WindowKind, display: Size) -> bool:
    """False for the keyboard and for a system strip. An application window shaped like a strip
    still can, because only the platform's own UI draws the bars."""
    if kind is WindowKind.INPUT_METHOD:
        return False
    return not (kind is WindowKind.SYSTEM and is_strip(root.attrs.bounds, display))


def is_strip(bounds: Rect, display: Size) -> bool:
    """A bar along one edge: as wide as the display along its top or bottom edge, or as tall as
    it down a side edge, and thin across the other way."""
    width, height = bounds.right - bounds.left, bounds.bottom - bounds.top
    along_top_or_bottom = width >= display.width and (bounds.top <= 0 or bounds.bottom >= display.height)
    along_a_side = height >= display.height and (bounds.left <= 0 or bounds.right >= display.width)
    return (along_top_or_bottom and height <= STRIP_FRACTION * display.height) or (
        along_a_side and width <= STRIP_FRACTION * display.width
    )
