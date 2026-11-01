"""Every input that lands on something is judged by what it lands on.

A deny rule is only as strong as the evidence its input gives it. These tests plant a rule's
words on the element an input lands on and on the screen around it, then send the input down
each path into the engine: a tap, a set-text, a scroll and Enter. Each one must be refused
before anything reaches the backend, and `permits` is the list of what the backend received."""

import tomllib

import pytest
from fakes import J7_SERIAL, FakePhone, info_for
from support import ROOT, FakeClock, node, screen_of

from agent_phone.cli.policy import DEFAULT_POLICY, load_policy, load_profile
from agent_phone.core.act.act import act
from agent_phone.core.act.intent import Click, Direction, Fill, Request, Scroll
from agent_phone.core.act.ledger import Ledger
from agent_phone.core.context import Context
from agent_phone.core.outcome import Acted, ErrorCode, Refused
from agent_phone.core.phone import Key, KeyName, SetText, Swipe
from agent_phone.core.policy.engine import Clear, ClearReason, Grant
from agent_phone.core.policy.rules import Effect, merge, parse_policy
from agent_phone.core.refs.resolve import RefTarget
from agent_phone.core.refs.store import SnapshotStore
from agent_phone.core.snapshot.capture import capture
from agent_phone.core.snapshot.snapshot import SettleState

DEFAULT = parse_policy(tomllib.loads(DEFAULT_POLICY.read_text(encoding="utf-8")), "default.toml")
J7 = load_profile(ROOT / "examples" / "devices" / "j7.toml")
J7_POLICY = load_policy((), J7)
SEND = Grant(frozenset({Effect.SEND}))


def start(root, screen, policy, locale="en-US", profile=None):
    root.mkdir(exist_ok=True)
    info = info_for(J7_SERIAL, locale=locale)
    phone = FakePhone(info, screen)
    ctx = Context(phone, info, profile, policy, SnapshotStore(root), Ledger(root, info.identity), FakeClock())
    return ctx, phone, capture(ctx, phone.read(), settled=SettleState.SETTLED)


def ref(taken, role):
    [line] = [line for line in taken.lines if line.role.value == role and line.ref is not None]
    return RefTarget(taken.ref(line.ref))


def form(title="Details", hint="Alias", list_words="Entries", package="test.app", focused=True):
    """A titled screen with a list that scrolls and, inside it, one text field."""
    return screen_of(
        node(
            "android.widget.FrameLayout",
            node("android.widget.TextView", text=title, bounds="[0,63][1080,200]"),
            node(
                "android.widget.ScrollView",
                node(
                    "android.widget.EditText",
                    hint=hint,
                    clickable=True,
                    focused=focused,
                    bounds="[0,300][1080,420]",
                ),
                scrollable=True,
                content_desc=list_words,
                bounds="[0,200][1080,1500]",
            ),
            node("android.widget.Button", text="Save", clickable=True, bounds="[0,1700][1080,1800]"),
            package=package,
            bounds="[0,0][1080,1920]",
        )
    )


def request_for(path, taken, grant):
    match path:
        case "tap":
            return Request(Click(ref(taken, "field")), grant)
        case "set-text":
            return Request(Fill(ref(taken, "field"), "hello"), grant)
        case "scroll":
            return Request(Scroll(ref(taken, "scroll"), Direction.DOWN), grant)
        case _:
            return Request(Key(KeyName.ENTER), grant)


PATHS = ["tap", "set-text", "scroll", "enter"]


def denying(**rule):
    deny = {"id": "t.deny", "reason": "A test denial.", **rule}
    return merge((DEFAULT, parse_policy({"deny": [deny]}, "consumer.toml")))


@pytest.mark.parametrize("path", PATHS)
def test_a_deny_rule_reads_the_words_of_the_element_each_input_lands_on(tmp_path, path):
    words = {"list_words": "plant"} if path == "scroll" else {"hint": "plant"}
    ctx, phone, taken = start(tmp_path, form(**words), denying(words=["plant"]))
    outcome = act(ctx, request_for(path, taken, SEND))
    assert phone.permits == [], f"{path} reached the backend with the deny rule's words on its element"
    assert isinstance(outcome, Refused) and outcome.code is ErrorCode.DENIED, outcome


@pytest.mark.parametrize("path", PATHS)
def test_a_deny_rule_reads_the_screen_around_the_element_each_input_lands_on(tmp_path, path):
    ctx, phone, taken = start(tmp_path, form(title="plant"), denying(context_words=["plant"]))
    outcome = act(ctx, request_for(path, taken, SEND))
    assert phone.permits == [], f"{path} reached the backend on a screen the deny rule names"
    assert isinstance(outcome, Refused) and outcome.code is ErrorCode.DENIED, outcome


@pytest.mark.parametrize("path", PATHS)
def test_a_deny_rule_scoped_to_an_app_judges_each_input_in_that_app_only(tmp_path, path):
    around = {"context_words": ["plant"]}
    ctx, _, taken = start(
        tmp_path / "elsewhere", form(title="plant"), denying(packages=["other.app"], **around)
    )
    assert isinstance(act(ctx, request_for(path, taken, SEND)), Acted), "another app's rule applied"
    ctx, phone, taken = start(
        tmp_path / "here", form(title="plant"), denying(packages=["test.app"], **around)
    )
    outcome = act(ctx, request_for(path, taken, SEND))
    assert phone.permits == [], f"{path} was sent in the app the rule names"
    assert isinstance(outcome, Refused) and outcome.code is ErrorCode.DENIED


def tunnel_screen():
    return screen_of(
        node(
            "android.widget.FrameLayout",
            node("android.widget.TextView", text="SocksTun", bounds="[0,63][1080,200]"),
            node(
                "android.widget.ScrollView",
                node(
                    "android.widget.EditText",
                    text="10.0.0.1",
                    hint="Server",
                    clickable=True,
                    focused=True,
                    bounds="[0,300][1080,420]",
                ),
                scrollable=True,
                bounds="[0,200][1080,1500]",
            ),
            node("android.widget.Button", text="Save", clickable=True, bounds="[0,1700][1080,1800]"),
            package="hev.sockstun",
            bounds="[0,0][1080,1920]",
        )
    )


@pytest.mark.parametrize("path", PATHS)
def test_nothing_is_sent_on_a_screen_that_shows_the_tunnel_on_the_j7(tmp_path, path):
    ctx, phone, taken = start(tmp_path, tunnel_screen(), J7_POLICY, profile=J7.profile)
    outcome = act(ctx, request_for(path, taken, SEND))
    assert phone.permits == [], f"{path} was sent on SocksTun's own screen"
    assert isinstance(outcome, Refused) and outcome.code is ErrorCode.DENIED
    assert outcome.details["rule"] == "j7.sockstun-screens"


def test_back_home_and_recents_leave_a_screen_that_a_deny_rule_names(tmp_path):
    ctx, phone, _ = start(tmp_path, tunnel_screen(), J7_POLICY, profile=J7.profile)
    for key in (KeyName.BACK, KeyName.HOME, KeyName.RECENTS):
        assert isinstance(act(ctx, Request(Key(key))), Acted), (
            f"{key.value} was refused: the agent is trapped"
        )
        capture(ctx, phone.read(), settled=SettleState.SETTLED)
    assert [permit.action for permit in phone.permits] == [
        Key(KeyName.BACK),
        Key(KeyName.HOME),
        Key(KeyName.RECENTS),
    ]


def test_set_text_and_scroll_commit_nothing_even_where_the_screen_says_send(tmp_path):
    composer = form(hint="Send a message", list_words="Delete all", title="Reply to a post")
    ctx, phone, taken = start(tmp_path / "text", composer, merge((DEFAULT,)))
    typed = act(ctx, Request(Fill(ref(taken, "field"), "hello")))
    assert isinstance(typed, Acted) and typed.report.verdict == Clear(ClearReason.NOT_LABELED_INPUT)
    assert [type(permit.action) for permit in phone.permits] == [SetText]
    ctx, phone, taken = start(tmp_path / "scroll", composer, merge((DEFAULT,)))
    scrolled = act(ctx, Request(Scroll(ref(taken, "scroll"), Direction.DOWN)))
    assert isinstance(scrolled, Acted) and scrolled.report.verdict == Clear(ClearReason.NOT_LABELED_INPUT)
    assert [type(permit.action) for permit in phone.permits] == [Swipe]


def test_set_text_in_a_language_the_rules_do_not_cover_is_judged_by_deny_rules_only(tmp_path):
    ctx, phone, taken = start(tmp_path, form(), merge((DEFAULT,)), locale="de-DE")
    assert isinstance(act(ctx, Request(Fill(ref(taken, "field"), "hallo"))), Acted)
    assert [type(permit.action) for permit in phone.permits] == [SetText]


def focused_button(label, **attrs):
    return node(
        "android.widget.Button",
        text=label,
        clickable=True,
        focused=True,
        bounds="[540,1700][1080,1800]",
        **attrs,
    )


def dialog(title, focused):
    return screen_of(
        node(
            "android.widget.FrameLayout",
            node("android.widget.TextView", text=title, bounds="[0,1500][1080,1600]"),
            node("android.widget.Button", text="Cancel", clickable=True, bounds="[0,1700][540,1800]"),
            focused,
            bounds="[0,1400][1080,1900]",
        )
    )


def test_enter_with_a_send_grant_does_not_press_a_focused_delete_button(tmp_path):
    ctx, phone, taken = start(
        tmp_path, dialog("Delete this post?", focused_button("Delete")), merge((DEFAULT,))
    )
    outcome = act(ctx, Request(Key(KeyName.ENTER), SEND))
    assert phone.permits == [], "Enter pressed the focused Delete button under a grant for send only"
    assert isinstance(outcome, Refused) and outcome.code is ErrorCode.COMMIT_REFUSED
    assert set(outcome.details["effects"]) == {"send", "delete"}


def test_enter_on_a_focused_neutral_button_does_what_its_dialog_says(tmp_path):
    screen = dialog("Delete this post?", focused_button("OK"))
    ctx, phone, taken = start(tmp_path, screen, merge((DEFAULT,)))
    outcome = act(ctx, Request(Key(KeyName.ENTER), SEND))
    assert phone.permits == [], "Enter pressed a focused OK under a delete question"
    assert isinstance(outcome, Refused) and outcome.code is ErrorCode.COMMIT_REFUSED
    assert "delete" in outcome.details["effects"]


def test_enter_on_a_focused_field_commits_send_by_the_key_alone(tmp_path):
    ctx, phone, taken = start(tmp_path, form(hint="Search"), merge((DEFAULT,)))
    refused = act(ctx, Request(Key(KeyName.ENTER)))
    assert isinstance(refused, Refused) and refused.code is ErrorCode.COMMIT_REFUSED
    assert refused.details["effects"] == ["send"]
    assert isinstance(act(ctx, Request(Key(KeyName.ENTER), SEND)), Acted)


def test_enter_in_a_language_the_rules_do_not_cover_is_not_judged_and_so_not_sent(tmp_path):
    ctx, phone, taken = start(tmp_path, form(), merge((DEFAULT,)), locale="de-DE")
    outcome = act(ctx, Request(Key(KeyName.ENTER), SEND))
    assert phone.permits == [], "Enter was sent on a screen whose words the engine cannot read"
    assert isinstance(outcome, Refused) and outcome.code is ErrorCode.LOCALE_UNSUPPORTED


def test_enter_with_nothing_in_focus_still_lets_a_rule_read_the_screen(tmp_path):
    ctx, phone, taken = start(tmp_path, form(title="plant", focused=False), denying(context_words=["plant"]))
    outcome = act(ctx, Request(Key(KeyName.ENTER), SEND))
    assert phone.permits == [], "Enter was sent with no focused view on a screen the rule names"
    assert isinstance(outcome, Refused) and outcome.code is ErrorCode.DENIED
