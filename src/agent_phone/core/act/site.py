"""The `Site` of an input: what the engine reads for it, built from the screen act() just read.

A deny rule is only as strong as the evidence its input path hands it, so every input that lands
on something gets the same kind of site:

- a tap, a long press, a set-text and a scroll land on the node act() planned them for;
- Enter lands on the view that has focus, because Android hands the key to that view and a
  focused clickable view clicks on it.

The receiver is the node's label surface, with the words of its row added for a toggle, and the
context is the rest of its window. Whether commit rules read them too is the engine's call
(`reads.reads_of`), not this module's.

Back, home and recents get no site from here. They are the agent's way off a screen, and a deny
rule that traps the agent on the screen is worse than the screen.
"""

from __future__ import annotations

from agent_phone.core.act.hit import context_labels, outside_labels, row_labels
from agent_phone.core.labels import Surface, owned, surface_of
from agent_phone.core.policy.engine import Site
from agent_phone.core.role import CHOICES, role_of
from agent_phone.core.screen import Flag, Node, Screen


def receiver_of(screen: Screen, node: Node) -> Surface:
    """A toggle often says only "On" or "Off", and its row says what it turns on."""
    surface = surface_of(screen, node)
    if role_of(node.attrs) in CHOICES:
        return Surface(node.id, surface.labels + row_labels(screen, node))
    return surface


def element_site(screen: Screen, node: Node) -> Site:
    window = screen.window_of(node.id)
    return Site(window.package, window.kind, receiver_of(screen, node), context_labels(screen, node))


def focus_site(screen: Screen, fallback: Site) -> Site:
    """The site of Enter: the focused node of the active window, as a tap on it would be judged.
    With nothing focused there is no receiver, and the context is every label of the window, so
    a rule that names the screen still sees it. With no active window `fallback` stands, and
    nothing can hold focus there."""
    window = screen.active_window()
    if window is None:
        return fallback
    focused = [node for node in screen.subtree(window.root) if node.has(Flag.FOCUSED)]
    if not focused:
        return Site(window.package, window.kind, None, outside_labels(screen, window, set()))
    surfaces = [receiver_of(screen, node) for node in focused]
    receiver = Surface(surfaces[0].owner, tuple(label for surface in surfaces for label in surface.labels))
    own = {member.id for node in focused for member in owned(screen, node)}
    return Site(window.package, window.kind, receiver, outside_labels(screen, window, own))
