"""Shared test inputs: the redacted fixture dumps and a builder for small synthetic dumps."""

from pathlib import Path
from xml.sax.saxutils import quoteattr

from agent_phone.adapters.uiautomator2.parse import parse_hierarchy
from agent_phone.core.geometry import Size
from agent_phone.core.screen import Screen

ROOT = Path(__file__).resolve().parents[1]
DUMPS = ROOT / "tests" / "fixtures" / "dumps"
GOLDEN = ROOT / "tests" / "golden"
FIXTURES = ("ig-feed", "mbs-home", "notification-shade", "settings-home")
J7 = Size(1080, 1920)


def fixture_xml(name: str) -> str:
    return (DUMPS / f"{name}.xml").read_text()


def fixture_screen(name: str) -> Screen:
    return parse_hierarchy(fixture_xml(name), J7, ime_package=None)


def node(cls: str = "android.view.View", *children: str, **attrs: object) -> str:
    """One `<node>` element. Keyword names use `_` for the dump's `-`: `content_desc="Home"`."""
    values: dict[str, object] = {
        "class": cls,
        "package": "test.app",
        "bounds": "[0,0][100,100]",
        "enabled": True,
        "visible-to-user": True,
    }
    values.update({key.replace("_", "-"): value for key, value in attrs.items()})
    rendered = " ".join(f"{key}={quoteattr(encode(value))}" for key, value in values.items())
    return f"<node {rendered}>{''.join(children)}</node>"


def encode(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def dump(*windows: str, rotation: int = 0) -> str:
    return f'<hierarchy rotation="{rotation}">{"".join(windows)}</hierarchy>'


def screen_of(*windows: str, rotation: int = 0, ime_package: str | None = None) -> Screen:
    return parse_hierarchy(dump(*windows, rotation=rotation), J7, ime_package=ime_package)
