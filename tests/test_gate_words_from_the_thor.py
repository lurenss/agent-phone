"""Labels the gate must read as commits, from what unit 7 saw on Lorenzo's AYN Thor (A6-9).

YouTube's Iscriviti and Chess's Inizia partita and Sfida un amico are the Thor's own labels.
The call and join labels are written for this test: no call or join button was on any screen
read, and the default had no word for either. Chess's start of a rated game against a stranger is
a commit only that app's rules can name. Each label is tapped the way `act()` judges a tap: the
button's own words and the rest of its window.

The consent cases at the end are the buttons that A6-9 names (Netflix's ad-consent screen and
Grok's Authorize), A6-3 (the Bluetooth discoverable request) and Android's own Allow and Don't
allow. Their raw dumps are not kept, so each screen is rebuilt from the labels, and the question
above the buttons is a stand-in that holds no commit word."""

import pytest
from fakes import FakePhone, info_for
from support import ROOT, FakeClock, node, screen_of

from agent_phone.cli.policy import load_policy, load_profile
from agent_phone.core.act.act import act
from agent_phone.core.act.hit import context_labels, plan_point, receiver_at
from agent_phone.core.act.intent import Click, Request
from agent_phone.core.act.ledger import Ledger
from agent_phone.core.context import Context
from agent_phone.core.device import Package
from agent_phone.core.labels import surface_of
from agent_phone.core.outcome import Acted, ErrorCode, Refused
from agent_phone.core.phone import NodeAddress, Tap
from agent_phone.core.policy.engine import Clear, Commits, Site, classify
from agent_phone.core.refs.resolve import RefTarget
from agent_phone.core.refs.store import SnapshotStore
from agent_phone.core.snapshot.capture import capture
from agent_phone.core.snapshot.snapshot import SettleState

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


NETFLIX = "com.netflix.mediaclient"
GROK = "ai.x.grok.bot"
SETTINGS = "com.android.settings"
CONSENT_SCREENS = {
    "netflix": (
        NETFLIX,
        "Ti mostreremo annunci pertinenti",
        ("Accetta e continua", "Rifiuta e continua", "Modifica preferenze"),
    ),
    "grok": (GROK, "Grok vuole accedere al tuo account Stripe", ("Annulla", "Authorize")),
    "bluetooth": (
        SETTINGS,
        "Un'app vuole rendere il dispositivo visibile ad altri dispositivi Bluetooth per 120 secondi.",
        ("RIFIUTA", "CONSENTI"),
    ),
    "permission": (
        "com.google.android.permissioncontroller",
        "Consentire all'app di inviarti notifiche?",
        ("Don't allow", "Allow"),
    ),
}


def consent_screen(package: str, question: str, buttons: tuple[str, ...]):
    """A dialog: its question above, and its buttons side by side. A real screen holds more, but a
    consent button is judged by its own words and, as an affirmative, by this question."""
    width = 1080 // len(buttons)
    return screen_of(
        node(
            "android.widget.FrameLayout",
            node("android.widget.TextView", text=question, bounds="[0,1400][1080,1500]", package=package),
            *(
                node(
                    "android.widget.Button",
                    text=label,
                    clickable=True,
                    bounds=f"[{i * width},1700][{(i + 1) * width},1800]",
                    package=package,
                )
                for i, label in enumerate(buttons)
            ),
            package=package,
            bounds="[0,1350][1080,1900]",
        )
    )


def tap_in_act(root, screen, label: str) -> set[str]:
    """What `act()` makes of a tap on `label` on the Thor with its profile: the effects it refuses
    for lack of a grant, or nothing when it sends the tap. Nothing else may happen."""
    info = info_for(THOR.profile.serial, locale=LOCALE)
    phone = FakePhone(info, screen)
    ctx = Context(
        phone,
        info,
        THOR.profile,
        load_policy([], THOR),
        SnapshotStore(root),
        Ledger(root, info.identity),
        FakeClock(),
    )
    taken = capture(ctx, phone.read(), settled=SettleState.SETTLED)
    [line] = [line for line in taken.lines if line.name == label]
    outcome = act(ctx, Request(Click(RefTarget(taken.ref(line.ref)))))
    if isinstance(outcome, Refused):
        assert outcome.code is ErrorCode.COMMIT_REFUSED, outcome
        assert phone.permits == []
        return set(outcome.details["effects"])
    assert isinstance(outcome, Acted) and len(phone.permits) == 1, outcome
    return set()


NO_CONSENT_YET = pytest.mark.xfail(strict=True, reason="the consent effect does not exist yet")


@pytest.mark.parametrize(
    ("screen", "label", "effects"),
    [
        pytest.param("netflix", "Accetta e continua", {"consent"}, marks=NO_CONSENT_YET),
        ("netflix", "Rifiuta e continua", set()),
        ("netflix", "Modifica preferenze", set()),
        pytest.param("grok", "Authorize", {"consent"}, marks=NO_CONSENT_YET),
        ("grok", "Annulla", set()),
        pytest.param("bluetooth", "CONSENTI", {"consent"}, marks=NO_CONSENT_YET),
        ("bluetooth", "RIFIUTA", set()),
        pytest.param("permission", "Allow", {"consent"}, marks=NO_CONSENT_YET),
        ("permission", "Don't allow", set()),
    ],
)
def test_the_thors_consent_buttons_are_consent_and_their_declines_are_clear(tmp_path, screen, label, effects):
    assert tap_in_act(tmp_path, consent_screen(*CONSENT_SCREENS[screen]), label) == effects
