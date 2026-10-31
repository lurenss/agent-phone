"""Shared test inputs: the redacted fixture dumps and a builder for small synthetic dumps."""

from pathlib import Path
from xml.sax.saxutils import quoteattr

from agent_phone.adapters.uiautomator2.parse import parse_hierarchy
from agent_phone.core.device import DeviceIdentity
from agent_phone.core.geometry import Size
from agent_phone.core.refs.fingerprint import fingerprints
from agent_phone.core.role import consumes_touch
from agent_phone.core.screen import Node, NodeId, Screen
from agent_phone.core.snapshot.budget import fit
from agent_phone.core.snapshot.snapshot import SettleState, Snapshot, SnapshotId
from agent_phone.core.snapshot.surface import select_surface
from agent_phone.core.snapshot.view import Mode, View, build_view

ROOT = Path(__file__).resolve().parents[1]
DUMPS = ROOT / "tests" / "fixtures" / "dumps"
GOLDEN = ROOT / "tests" / "golden"
FIXTURES = ("ig-feed", "mbs-home", "notification-shade", "settings-home")
J7 = Size(1080, 1920)


def fixture_xml(name: str) -> str:
    return (DUMPS / f"{name}.xml").read_text()


def fixture_screen(name: str) -> Screen:
    return parse_hierarchy(fixture_xml(name), J7, ime_package=None)


def compact(screen: Screen, root: NodeId | None = None) -> View:
    return build_view(select_surface(screen, root=root), Mode.COMPACT)


def snapshot_of(screen: Screen, id: SnapshotId, device: DeviceIdentity, epoch: int = 0) -> Snapshot:
    """What `capture` will record for this screen, built without a device or a ledger."""
    surface = select_surface(screen)
    view = fit(build_view(surface, Mode.COMPACT), id)
    return Snapshot(
        id=id,
        device=device,
        epoch=epoch,
        package=surface.window.package,
        window_kind=surface.window.kind,
        mode=view.mode,
        settled=SettleState.UNCHECKED,
        keyboard=surface.keyboard,
        dialog=surface.dialog,
        others=surface.others,
        toasts=screen.toasts,
        lines=view.lines,
        fingerprints=fingerprints(view),
        truncated=0,
    )


def labelled(screen: Screen, value: str) -> Node:
    """The one node whose own text or content-desc is `value`."""
    found = [n for n in screen.nodes if value in (n.attrs.text, n.attrs.content_desc)]
    assert len(found) == 1, f"{len(found)} nodes say {value!r}"
    return found[0]


def consumer_of(screen: Screen, node_: Node) -> Node:
    """The node a tap on `node_` reaches: itself or its nearest touch-consuming ancestor."""
    return next(n for n in (node_, *screen.ancestors(node_.id)) if consumes_touch(n.attrs))


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


class FakeClock:
    """Time that only moves when something pauses, so a bounded wait runs in no real time."""

    def __init__(self) -> None:
        self.time = 0.0
        self.pauses: list[float] = []

    def now(self) -> float:
        return self.time

    def pause(self, seconds: float) -> None:
        self.pauses.append(seconds)
        self.time += seconds
