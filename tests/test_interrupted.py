"""An input whose target a recognised pop-up covers: it ends early, sends nothing and dismisses
nothing. Every case is checked against the inputs the fake phone received."""

from fakes import J7_SERIAL, FakeHub, invoke
from support import FakeClock, node, screen_of
from test_interruptions import ANR, J7, SHOP, context, dialog

from agent_phone.core.act.act import act
from agent_phone.core.act.intent import Click, Request
from agent_phone.core.outcome import Acted, ErrorCode, Refused
from agent_phone.core.phone import Tap
from agent_phone.core.query import Q
from agent_phone.core.refs.resolve import QueryTarget, RefTarget
from agent_phone.core.snapshot.capture import capture
from agent_phone.core.snapshot.snapshot import SnapshotId
from agent_phone.core.wait.clock import POLL_GAP_S


def app(*buttons, package=SHOP):
    """A full-screen app window with one button per label, top to bottom."""
    return node(
        "android.widget.FrameLayout",
        *(
            node(
                "android.widget.Button",
                text=label,
                package=package,
                clickable=True,
                bounds=f"[100,{200 + 200 * i}][980,{300 + 200 * i}]",
            )
            for i, label in enumerate(buttons)
        ),
        package=package,
        bounds="[0,0][1080,1920]",
    )


SHARE = screen_of(app("Share"))
NOT_RESPONDING = dialog("Example isn't responding", "Close app", "Wait")


def sent(hub):
    return [permit.action for phone in hub.phones for permit in phone.permits]


def test_a_click_under_a_known_dialog_is_interrupted_and_nothing_is_sent(tmp_path):
    invoke(["snapshot"], FakeHub([J7], screens=[SHARE]), tmp_path)
    hub, clock = FakeHub([J7], screens=[ANR]), FakeClock()
    code, wire = invoke(["click", "name=Share"], hub, tmp_path, clock=clock)
    assert code == 1 and wire["error"]["code"] == "INTERRUPTED"
    assert (wire["delivery"], wire["retry"]) == ("not_delivered", "safe")
    assert clock.time == 0 and hub.phones[0].reads == 1, "it ends on the first read"
    details = wire["error"]["details"]
    assert details["interruptions"] == [
        {
            "rule": "default.not-responding.en",
            "kind": "not_responding",
            "needs_human": False,
            "dismiss": f"@{details['snapshot']}:e2",
        }
    ]
    assert sent(hub) == [], "nothing is sent, and the pop-up is not dismissed"
    code, wire = invoke(["click", details["interruptions"][0]["dismiss"]], hub, tmp_path)
    assert code == 0, "the epoch was left, so the way out is a live ref for the caller to click"
    [tap] = sent(hub)
    assert wire["data"]["target"]["name"] == "Wait" and isinstance(tap, Tap)


def test_a_ref_in_a_window_that_lost_focus_to_a_pop_up_is_interrupted_at_once(tmp_path):
    _, taken = invoke(["snapshot"], FakeHub([J7], screens=[SHARE]), tmp_path)
    hub, clock = FakeHub([J7], screens=[screen_of(NOT_RESPONDING, app("Share"))]), FakeClock()
    code, wire = invoke(["click", f"@{taken['data']['id']}:e1"], hub, tmp_path, clock=clock)
    assert code == 1 and wire["error"]["code"] == "INTERRUPTED" and wire["retry"] == "safe"
    assert hub.phones[0].reads == 2, "a ref must sit still on two reads before its point is planned"
    assert clock.time == POLL_GAP_S and sent(hub) == []
    assert "not_responding" in wire["error"]["message"] and wire["error"]["hint"]


def test_a_missing_target_with_no_pop_up_still_waits_its_whole_timeout(tmp_path):
    invoke(["snapshot"], FakeHub([J7], screens=[SHARE]), tmp_path)
    hub, clock = FakeHub([J7], screens=[screen_of(dialog("Loading", "Hide"))]), FakeClock()
    code, wire = invoke(["click", "name=Share", "--timeout-ms", "300"], hub, tmp_path, clock=clock)
    assert code == 1 and wire["error"]["code"] == "NOT_FOUND"
    assert 0.3 <= clock.time < 0.4 and sent(hub) == []


def test_a_button_of_the_pop_up_itself_is_never_interrupted(tmp_path):
    """The keyboard covers the pop-up's own button: that is OCCLUDED, which may clear, as before."""
    keyboard = node("android.widget.FrameLayout", package="com.example.keys", bounds="[0,860][1080,1920]")
    covered = screen_of(NOT_RESPONDING, keyboard, ime_package="com.example.keys")
    _, taken = invoke(["snapshot"], FakeHub([J7], screens=[ANR]), tmp_path)
    hub, clock = FakeHub([J7], screens=[covered]), FakeClock()
    wait = f"@{taken['data']['id']}:e2"
    code, wire = invoke(["click", wait, "--timeout-ms", "300"], hub, tmp_path, clock=clock)
    assert code == 1 and wire["error"]["code"] == "OCCLUDED" and clock.time >= 0.3


def test_a_consumers_pop_up_ends_the_wait_and_asks_for_a_human_when_its_rule_says_so(tmp_path):
    rules = tmp_path / "shop.toml"
    rules.write_text(
        '[[interruption]]\nid = "shop.rate-us"\nkind = "promo"\npackages = ["com.example.shop"]\n'
        'words = ["rate us", "not now"]\ndismiss = ["Not now"]\nneeds_human = true\n'
        'reason = "The shop asks for a rating."\n'
    )
    invoke(["snapshot"], FakeHub([J7], screens=[SHARE]), tmp_path)
    sheet = screen_of(dialog("Enjoying Example Shop? Rate us", "Not now", "Rate", package=SHOP))
    hub, clock = FakeHub([J7], screens=[sheet]), FakeClock()
    code, wire = invoke(["click", "name=Share", "--policy", str(rules)], hub, tmp_path, clock=clock)
    details = wire["error"]["details"]
    assert wire["error"]["code"] == "INTERRUPTED" and clock.time == 0 and sent(hub) == []
    assert details["interruptions"] == [
        {
            "rule": "shop.rate-us",
            "kind": "promo",
            "needs_human": True,
            "dismiss": f"@{details['snapshot']}:e1",
        }
    ]


def test_the_interrupted_read_is_recorded_and_the_epoch_and_earlier_refs_stay(tmp_path):
    ctx = context(tmp_path, ANR)
    before = capture(ctx, ctx.phone.read())
    outcome = act(ctx, Request(Click(QueryTarget(Q(name="Share")))))
    assert isinstance(outcome, Refused) and outcome.code is ErrorCode.INTERRUPTED
    assert (
        ctx.ledger.epoch() == before.epoch == 0
        and not (tmp_path / "devices" / J7_SERIAL / "ledger.json").exists()
    )
    assert ctx.store.load(SnapshotId(outcome.details["snapshot"])).epoch == 0
    sent_after = act(ctx, Request(Click(RefTarget(before.ref(2)))))
    assert isinstance(sent_after, Acted) and [type(p.action) for p in ctx.phone.permits] == [Tap]


def test_a_page_whose_words_match_a_rule_still_waits_for_a_target_that_loads(tmp_path):
    def page(*more):
        return screen_of(app("Allow tags from everyone", "Don\u2019t allow", *more))

    invoke(["snapshot"], FakeHub([J7], screens=[page()]), tmp_path)
    hub, clock = FakeHub([J7], screens=[page(), page(), page("Learn more")]), FakeClock()
    code, wire = invoke(["click", "name=Learn more"], hub, tmp_path, clock=clock)
    assert code == 0 and [type(action) for action in sent(hub)] == [Tap]


def test_a_pop_up_that_lost_focus_or_a_disabled_target_keeps_waiting(tmp_path):
    opened = screen_of(app("Open"))
    _, taken = invoke(["snapshot"], FakeHub([J7], screens=[opened]), tmp_path)
    ref = f"@{taken['data']['id']}:e1"
    leaving = screen_of(
        app("Open"), dialog("Example isn't responding", "Close app", "Wait").replace("[60,650]", "[60,150]")
    )
    hub = FakeHub([J7], screens=[leaving, leaving, opened])
    code, wire = invoke(["click", ref], hub, tmp_path, clock=FakeClock())
    assert code == 0 and [type(action) for action in sent(hub)] == [Tap], wire
    disabled = node(
        "android.widget.Button",
        text="Open",
        package=SHOP,
        clickable=True,
        enabled=False,
        bounds="[100,200][980,300]",
    )
    window = node("android.widget.FrameLayout", disabled, package=SHOP, bounds="[0,0][1080,1920]")
    _, taken = invoke(["snapshot"], FakeHub([J7], screens=[opened]), tmp_path / "second")
    hub, clock = FakeHub([J7], screens=[screen_of(NOT_RESPONDING, window)]), FakeClock()
    argv = ["click", f"@{taken['data']['id']}:e1", "--timeout-ms", "300"]
    code, wire = invoke(argv, hub, tmp_path / "second", clock=clock)
    assert wire["error"]["code"] == "NOT_ACTIONABLE" and clock.time >= 0.3
