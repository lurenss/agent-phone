"""Labels from Lorenzo's AYN Thor that the gate must read as commits (A6-9).

YouTube's subscribe button, a call button of a messaging app and the join of a server or a call
passed the default policy as clear, and Chess's start of a rated game against a stranger is a
commit only that app's rules can name. Each label is tapped the way `act()` judges a tap: the
button's own words and the rest of its window."""

import pytest
from support import ROOT, node, screen_of

from agent_phone.cli.policy import load_policy, load_profile
from agent_phone.core.act.hit import context_labels, plan_point, receiver_at
from agent_phone.core.device import Package
from agent_phone.core.labels import surface_of
from agent_phone.core.phone import NodeAddress, Tap
from agent_phone.core.policy.engine import Clear, Commits, Site, classify

THOR = load_profile(ROOT / "examples" / "devices" / "thor.toml")
LOCALE = "it-VA"


def effects_of_a_tap(label: str, package: str, policy) -> set[str]:
    screen = screen_of(
        node(
            "android.widget.FrameLayout",
            node("android.widget.Button", text=label, clickable=True, bounds="[0,0][400,100]"),
            bounds="[0,0][1080,1920]",
            package=package,
        )
    )
    button = screen.nodes[1]
    point = plan_point(screen, button)
    receiver = screen.node(receiver_at(screen, screen.windows[0], point))
    site = Site(
        Package(package),
        screen.windows[0].kind,
        surface_of(screen, receiver),
        context_labels(screen, receiver),
    )
    address = NodeAddress(Package(package), "", "", "", "", button.attrs.bounds, (0,), None)
    verdict = classify(policy, Tap(point, address), site, LOCALE)
    assert isinstance(verdict, Clear | Commits), verdict
    return {effect.value for effect in verdict.effects} if isinstance(verdict, Commits) else set()


@pytest.mark.parametrize(
    ("label", "effects"),
    [
        ("Iscriviti a Lofi Hip Hop (tema).", {"social"}),
        ("Avvia chiamata vocale", {"send"}),
        ("Avvia videochiamata", {"send"}),
        ("Start a video call", {"send"}),
        ("Call", {"send"}),
        ("Partecipa alla chiamata vocale", {"send", "social"}),
        ("Join server", {"social"}),
        ("Unisciti al server", {"social"}),
    ],
)
def test_the_default_reads_a_subscribe_a_call_and_a_join_as_commits(label, effects):
    assert effects_of_a_tap(label, "test.app", load_policy([])) == effects


@pytest.mark.parametrize("label", ["Inizia partita", "Sfida un amico"])
def test_the_thor_profile_reads_the_start_of_a_chess_game_as_social(label):
    assert effects_of_a_tap(label, "com.chess", load_policy([], THOR)) == {"social"}


@pytest.mark.parametrize("label", ["Inizia partita", "Sfida un amico"])
def test_the_chess_words_are_scoped_to_the_chess_app(label):
    assert effects_of_a_tap(label, "test.app", load_policy([], THOR)) == set()
