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
- layer: None. The hit plan therefore treats every other window over a point as covering it
  (`core/act/hit.py`).

The `Screen` is the default display. Android 13 puts `display-id` on every node, and a device with a
second screen, such as the AYN Thor's bottom one (display 4), lists that screen's windows in the same
dump. The server's click and swipe are motion events on display 0, and keys go to the top focused
display, which is 0 on the Thor. A window of another display has coordinates of its own, so kept in the
`Screen` it would cover taps that belong to display 0 (every tap left of x=1240 on the Thor) or, as the
first window that could hold focus, become the active window with refs that no input can reach. The
parser therefore keeps the windows whose root has `display-id="0"` or none, which covers API 28 dumps,
and drops the rest: they are not active, not in `others`, not an occluder and not findable. Reading
another display is not supported.
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

EDGE_SLACK = 2
"""Pixels by which a window may stop short of a display edge and still be along it. The Thor reports
root bounds a pixel inside the display, and not always the same way: its status bar is `[1,0][1920,55]`
on one read and `[0,0][1920,55]` on another."""

DEFAULT_DISPLAY = "0"
"""The `display-id` of the display that input goes to. A dump without `display-id` (API 28) is all
on it."""

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
    """Raise `Refusal(TRANSPORT)` on XML that does not parse, `Refusal(NO_SURFACE)` when no window of
    display 0 is left (screen off, or a dump of other displays only). `natural_display` is swapped
    for rotation 1 and 3, as the landscape fixtures (`settings-home.xml`, `notification-shade.xml`)
    need."""
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
    roots = [
        root
        for root in hierarchy.findall("node")
        if root.get("display-id", DEFAULT_DISPLAY) == DEFAULT_DISPLAY
    ]
    if not roots:
        raise Refusal(
            ErrorCode.NO_SURFACE,
            "The screen dump has no window on the default display. The screen may be off.",
        )
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
    """A bar along one edge: as wide as the display along its top or bottom edge, or as tall as it
    down a side edge, and thin across the other way. "Along an edge" and "as wide as the display"
    both allow `EDGE_SLACK` pixels, so a bar that stops short of a side by more than that is not a strip."""
    near_left, near_top = bounds.left <= EDGE_SLACK, bounds.top <= EDGE_SLACK
    near_right = bounds.right >= display.width - EDGE_SLACK
    near_bottom = bounds.bottom >= display.height - EDGE_SLACK
    width, height = bounds.right - bounds.left, bounds.bottom - bounds.top
    along_top_or_bottom = near_left and near_right and (near_top or near_bottom)
    along_a_side = near_top and near_bottom and (near_left or near_right)
    return (along_top_or_bottom and height <= STRIP_FRACTION * display.height) or (
        along_a_side and width <= STRIP_FRACTION * display.width
    )
