"""act() on a fake phone: what reaches the device, what never does, and what the caller is told.

Every refusal below is checked against the fake's `permits`, the list of inputs the backend
received, so "sends no input" is an observation and not a claim."""

import tomllib

from fakes import EMULATOR_SERIAL, J7_SERIAL, FakePhone, info_for
from support import ROOT, FakeClock, checkbox_row, consumer_of, fixture_screen, labelled, node, screen_of

from agent_phone.cli.policy import DEFAULT_POLICY, load_profile
from agent_phone.core.act.act import act
from agent_phone.core.act.intent import Click, Direction, Fill, Request, Scroll
from agent_phone.core.act.ledger import Ledger
from agent_phone.core.context import Context
from agent_phone.core.device import BootId, DeviceProfile, Package, ProtectedPackage
from agent_phone.core.outcome import Acted, Disposition, ErrorCode, Refusal, Refused
from agent_phone.core.phone import Ack, Key, KeyName, Launch, NotSent, Sent, SetText, Stop, Swipe, Tap
from agent_phone.core.policy.engine import Clear, ClearReason, Grant
from agent_phone.core.policy.rules import Effect, Policy, merge, parse_policy, protect_rules
from agent_phone.core.query import Q
from agent_phone.core.refs.resolve import QueryTarget, RefTarget
from agent_phone.core.refs.store import SnapshotStore
from agent_phone.core.role import Role
from agent_phone.core.snapshot.capture import capture
from agent_phone.core.snapshot.snapshot import SettleState
from agent_phone.core.wait.predicate import Gone, Present

DEFAULT = parse_policy(tomllib.loads(DEFAULT_POLICY.read_text(encoding="utf-8")), "default.toml")
POLICY = merge((DEFAULT,))
SETTINGS = fixture_screen("settings-home")
DISPLAY_TILE = 7


def context(root, *screens, info=None, policy=POLICY, **fake):
    info = info or info_for(J7_SERIAL)
    phone = FakePhone(info, *screens, **fake)
    ctx = Context(phone, info, None, policy, SnapshotStore(root), Ledger(root, info.identity), FakeClock())
    return ctx, phone


def look(ctx, settled=SettleState.UNCHECKED):
    return capture(ctx, ctx.phone.read(), settled=settled)


def click(snapshot, number, **request):
    return Request(Click(RefTarget(snapshot.ref(number))), **request)


def refused(outcome, code):
    assert isinstance(outcome, Refused), outcome
    assert outcome.code is code, outcome
    return outcome


def with_rules(**tables):
    return merge((DEFAULT, parse_policy(tables, "consumer.toml")))


DISPLAY_COMMITS = {"id": "t.display", "effect": "confirm", "words": ["display"], "reason": "A test commit."}


def test_a_click_taps_its_tile_once_and_spends_every_ref_taken_before_it(tmp_path):
    ctx, phone = context(tmp_path, SETTINGS)
    taken = look(ctx)
    tile = consumer_of(SETTINGS, labelled(SETTINGS, "Display"))
    done = act(ctx, click(taken, DISPLAY_TILE))
    assert isinstance(done, Acted) and done.disposition is Disposition.DELIVERED_UNVERIFIED
    [permit] = phone.permits
    assert isinstance(permit.action, Tap) and permit.action.point == tile.attrs.bounds.center()
    assert permit.verdict == Clear(ClearReason.NO_COMMIT_WORDS) and permit.epoch == 1
    assert done.report.target.ref == f"@{taken.id}:e7" and done.report.target.name == "Display"
    again = refused(act(ctx, click(taken, 6)), ErrorCode.STALE_REF)
    assert again.details == {"reason": "spent"} and len(phone.permits) == 1


def test_a_ref_whose_element_left_the_screen_is_stale_and_sends_nothing(tmp_path):
    ctx, phone = context(tmp_path, SETTINGS, fixture_screen("dialog-over-app"))
    taken = look(ctx)
    gone = refused(act(ctx, click(taken, DISPLAY_TILE)), ErrorCode.STALE_REF)
    assert gone.details == {"reason": "gone"} and phone.permits == []


def test_a_ref_from_another_device_or_an_earlier_boot_is_refused_before_the_phone_is_read(tmp_path):
    j7, _ = context(tmp_path, SETTINGS)
    taken = look(j7)
    emulator, phone = context(tmp_path, SETTINGS, info=info_for(EMULATOR_SERIAL))
    refused(act(emulator, click(taken, DISPLAY_TILE)), ErrorCode.WRONG_DEVICE)
    assert phone.reads == 0 and phone.permits == []
    rebooted, phone = context(tmp_path, SETTINGS, info=info_for(J7_SERIAL, boot=BootId("a-later-boot")))
    stale = refused(act(rebooted, click(taken, DISPLAY_TILE)), ErrorCode.STALE_REF)
    assert stale.details == {"reason": "rebooted"} and phone.reads == 0 and phone.permits == []


def test_a_commit_is_refused_without_its_grant_and_a_deny_rule_even_with_one(tmp_path):
    ctx, phone = context(tmp_path, SETTINGS, policy=with_rules(commit=[DISPLAY_COMMITS]))
    taken = look(ctx)
    commit = refused(act(ctx, click(taken, DISPLAY_TILE)), ErrorCode.COMMIT_REFUSED)
    assert commit.details["effects"] == ["confirm"] and phone.permits == []
    refused(
        act(ctx, click(taken, DISPLAY_TILE, grant=Grant(frozenset({Effect.PUBLISH})))),
        ErrorCode.COMMIT_REFUSED,
    )
    deny = {"id": "t.no-display", "words": ["display"], "reason": "A test denial."}
    ctx, phone = context(tmp_path, SETTINGS, policy=with_rules(commit=[DISPLAY_COMMITS], deny=[deny]))
    taken = look(ctx)
    denied = refused(act(ctx, click(taken, DISPLAY_TILE, grant=Grant(frozenset(Effect)))), ErrorCode.DENIED)
    assert denied.details["rule"] == "t.no-display" and phone.permits == []
    assert ctx.ledger.epoch() == 0


def test_a_protected_package_is_never_stopped_and_another_is(tmp_path):
    profile = DeviceProfile(
        J7_SERIAL, "j7", (ProtectedPackage(Package("hev.sockstun"), ("SocksTun",), "VPN."),), ()
    )
    policy = merge((DEFAULT, (Policy(frozenset(), protect_rules(profile, "j7.toml")), frozenset())))
    ctx, phone = context(tmp_path, SETTINGS, policy=policy)
    look(ctx)
    denied = refused(act(ctx, Request(Stop(Package("hev.sockstun")))), ErrorCode.DENIED)
    assert denied.details["rule"] == "profile.protect.hev.sockstun.stop" and phone.permits == []
    stopped = act(ctx, Request(Stop(Package("com.android.settings"))))
    assert isinstance(stopped, Acted) and [p.action for p in phone.permits] == [
        Stop(Package("com.android.settings"))
    ]


def test_an_input_the_backend_proves_never_left_gives_its_refs_back(tmp_path):
    ctx, phone = context(tmp_path, SETTINGS, delivery=NotSent(ErrorCode.SERVER_UNAVAILABLE, "no server"))
    taken = look(ctx)
    refused(act(ctx, click(taken, DISPLAY_TILE)), ErrorCode.SERVER_UNAVAILABLE)
    assert ctx.ledger.epoch() == 0
    refused(act(ctx, click(taken, DISPLAY_TILE)), ErrorCode.SERVER_UNAVAILABLE)
    assert len(phone.permits) == 2 and ctx.ledger.epoch() == 0


def test_an_input_whose_answer_was_lost_is_uncertain(tmp_path):
    ctx, _ = context(tmp_path, SETTINGS, delivery=Sent(Ack.UNACKNOWLEDGED, "timeout"))
    done = act(ctx, click(look(ctx), DISPLAY_TILE))
    assert isinstance(done, Acted) and done.disposition is Disposition.DELIVERY_UNCERTAIN


DISPLAY_PAGE = screen_of(
    node(
        "android.widget.FrameLayout",
        node("android.widget.TextView", text="Brightness", bounds="[0,200][1080,300]"),
        node(
            "android.widget.ImageButton", content_desc="Navigate up", clickable=True, bounds="[0,0][150,150]"
        ),
        package="com.android.settings",
        bounds="[0,0][1080,1920]",
    )
)


def test_a_wait_that_saw_its_effect_appear_verifies_the_input_and_returns_fresh_refs(tmp_path):
    ctx, phone = context(tmp_path, SETTINGS, after_input=[DISPLAY_PAGE])
    done = act(ctx, click(look(ctx), DISPLAY_TILE, wait_for=(Present(Q("Brightness")),)))
    assert isinstance(done, Acted) and done.disposition is Disposition.DELIVERED_VERIFIED
    assert done.report.verified_by == 'present name="Brightness"'
    assert done.after is not None and done.after.epoch == 1
    back = act(ctx, click(done.after, 1))
    assert isinstance(back, Acted) and len(phone.permits) == 2


def test_a_wait_that_already_held_proves_nothing_and_one_that_never_holds_times_out(tmp_path):
    ctx, _ = context(tmp_path, SETTINGS)
    held = act(ctx, click(look(ctx), DISPLAY_TILE, wait_for=(Present(Q("Notifications")),)))
    assert isinstance(held, Acted) and held.disposition is Disposition.DELIVERED_UNVERIFIED
    assert held.report.verified_by == 'present name="Notifications", which already held before the input'
    ctx, _ = context(tmp_path, SETTINGS)
    late = act(ctx, click(look(ctx), DISPLAY_TILE, wait_for=(Gone(Q("Display")),), timeout_ms=300))
    assert isinstance(late, Acted) and late.error is ErrorCode.TIMEOUT
    assert late.disposition is Disposition.DELIVERED_UNVERIFIED and late.after is not None


def field(text: str = "", password: bool = False) -> str:
    return node(
        "android.widget.EditText",
        text=text,
        hint="Search",
        clickable=True,
        password=password,
        bounds="[0,100][1080,200]",
    )


def window(*children: str):
    return screen_of(node("android.widget.FrameLayout", *children, bounds="[0,0][1080,1920]"))


def test_set_text_writes_the_field_through_its_address_and_reads_it_back(tmp_path):
    ctx, phone = context(tmp_path, window(field()), after_input=[window(field("display"))])
    done = act(ctx, Request(Fill(RefTarget(look(ctx).ref(1)), "display")))
    assert isinstance(done, Acted) and done.disposition is Disposition.DELIVERED_VERIFIED
    [permit] = phone.permits
    assert isinstance(permit.action, SetText) and permit.action.text == "display" and not permit.action.secret
    assert permit.action.field.bounds == window(field()).nodes[1].attrs.bounds
    ctx, _ = context(tmp_path, window(field()), after_input=[window(field("dis"))])
    wrong = act(ctx, Request(Fill(RefTarget(look(ctx).ref(1)), "display")))
    assert isinstance(wrong, Acted) and wrong.error is ErrorCode.ACTION_FAILED
    assert wrong.disposition is Disposition.DELIVERED_UNVERIFIED


def test_a_secret_field_is_written_and_never_read_back(tmp_path):
    ctx, phone = context(tmp_path, window(field(password=True)))
    done = act(ctx, Request(Fill(RefTarget(look(ctx).ref(1)), "hunter2")))
    assert isinstance(done, Acted) and done.disposition is Disposition.DELIVERED_UNVERIFIED
    assert phone.permits[0].action.secret and phone.reads == 3


def save(enabled: bool, top: int = 500):
    return window(button("Save", top, enabled=enabled))


def button(label: str, top: int, **attrs):
    return node(
        "android.widget.Button", text=label, clickable=True, bounds=f"[0,{top}][1080,{top + 100}]", **attrs
    )


def test_a_disabled_target_is_waited_for_and_one_that_stays_disabled_is_refused(tmp_path):
    ctx, phone = context(tmp_path, save(False), save(False), save(False), save(True))
    done = act(ctx, click(look(ctx), 1))
    assert isinstance(done, Acted) and len(phone.permits) == 1
    ctx, phone = context(tmp_path, save(False))
    stuck = refused(act(ctx, click(look(ctx), 1, timeout_ms=200)), ErrorCode.NOT_ACTIONABLE)
    assert stuck.details == {"reason": "disabled"} and phone.permits == []


def test_a_target_that_keeps_moving_is_refused_as_unstable(tmp_path):
    moving = [window(button("Save", 500 + 10 * i)) for i in range(12)]
    ctx, phone = context(tmp_path, *moving)
    refused(act(ctx, click(look(ctx), 1, timeout_ms=200)), ErrorCode.UNSTABLE)
    assert phone.permits == []


def test_a_settled_snapshot_lets_an_unmoved_target_go_on_the_first_read(tmp_path):
    ctx, phone = context(tmp_path, SETTINGS)
    act(ctx, click(look(ctx, SettleState.SETTLED), DISPLAY_TILE))
    assert phone.reads == 2 and len(phone.permits) == 1


def test_a_query_target_must_match_exactly_one_element_of_a_current_observation(tmp_path):
    ctx, phone = context(tmp_path, SETTINGS)
    refused(act(ctx, Request(Click(QueryTarget(Q("Display"))))), ErrorCode.OBSERVE_FIRST)
    look(ctx)
    refused(act(ctx, Request(Click(QueryTarget(Q(role=Role.BUTTON))))), ErrorCode.AMBIGUOUS_TARGET)
    assert isinstance(act(ctx, Request(Click(QueryTarget(Q("Display"))))), Acted)
    assert (
        phone.permits[0].action.point
        == consumer_of(SETTINGS, labelled(SETTINGS, "Display")).attrs.bounds.center()
    )


def test_a_scroll_swipes_inside_the_list_against_the_direction(tmp_path):
    ctx, phone = context(tmp_path, SETTINGS)
    taken = look(ctx)
    act(ctx, Request(Scroll(RefTarget(taken.ref(3)), Direction.DOWN)))
    [permit] = phone.permits
    swipe, lists = permit.action, consumer_of(SETTINGS, labelled(SETTINGS, "Display"))
    assert isinstance(swipe, Swipe) and swipe.start.y > swipe.end.y and swipe.start.x == swipe.end.x
    tiles = SETTINGS.node(lists.parent)
    assert all(tiles.attrs.bounds.contains(point) for point in (swipe.start, swipe.end))
    not_a_list = refused(
        act(ctx, Request(Scroll(RefTarget(look(ctx).ref(7)), Direction.DOWN))), ErrorCode.NOT_ACTIONABLE
    )
    assert not_a_list.details == {"reason": "not_scrollable"}


def test_an_input_without_a_target_needs_a_current_observation_too(tmp_path):
    ctx, phone = context(tmp_path, SETTINGS)
    refused(act(ctx, Request(Key(KeyName.BACK))), ErrorCode.OBSERVE_FIRST)
    look(ctx)
    assert isinstance(act(ctx, Request(Key(KeyName.BACK))), Acted)
    refused(act(ctx, Request(Key(KeyName.BACK))), ErrorCode.OBSERVE_FIRST)
    look(ctx)
    refused(act(ctx, Request(Key(KeyName.ENTER))), ErrorCode.COMMIT_REFUSED)
    assert isinstance(act(ctx, Request(Launch(Package("com.android.settings")))), Acted)
    assert [p.action for p in phone.permits] == [Key(KeyName.BACK), Launch(Package("com.android.settings"))]


def test_a_labeled_input_on_a_device_whose_language_has_no_rules_is_refused(tmp_path):
    ctx, phone = context(tmp_path, SETTINGS, info=info_for(J7_SERIAL, locale="de-DE"))
    refused(act(ctx, click(look(ctx), DISPLAY_TILE)), ErrorCode.LOCALE_UNSUPPORTED)
    assert phone.permits == []


def settings_row(title: str, switch_clickable: bool) -> str:
    """A preference row: a clickable row whose switch widget is checkable, and clickable only
    when an app sets it so. AOSP's widget layout sets `android:clickable="false"`."""
    return node(
        "android.widget.LinearLayout",
        node(
            "android.widget.TextView", text=title, resource_id="android:id/title", bounds="[0,500][800,600]"
        ),
        node(
            "android.widget.Switch",
            text="Off",
            checkable=True,
            clickable=switch_clickable,
            resource_id="android:id/switch_widget",
            bounds="[880,500][1080,600]",
        ),
        clickable=True,
        bounds="[0,500][1080,600]",
    )


def test_a_switch_that_takes_no_touch_is_never_tapped_for_its_row(tmp_path):
    ctx, phone = context(tmp_path, window(settings_row("Airplane mode", switch_clickable=False)))
    refused(act(ctx, click(look(ctx, SettleState.SETTLED), 2)), ErrorCode.NOT_ACTIONABLE)
    assert phone.permits == []


def test_a_toggle_is_judged_with_the_title_of_its_row(tmp_path):
    row = node(
        "android.widget.LinearLayout",
        node("android.widget.TextView", text="Mobile data", bounds="[0,500][800,600]"),
        node(
            "android.widget.Switch", text="Off", checkable=True, clickable=True, bounds="[880,500][1080,600]"
        ),
        bounds="[0,500][1080,600]",
    )
    ctx, phone = context(tmp_path, window(row))
    commit = refused(act(ctx, click(look(ctx, SettleState.SETTLED), 1)), ErrorCode.COMMIT_REFUSED)
    assert commit.details["effects"] == ["system"] and phone.permits == []


ROW, CHECKBOX = 1, 2


def test_the_words_of_a_toggle_that_takes_no_touch_are_judged_for_the_row_that_takes_it(tmp_path):
    ctx, phone = context(tmp_path, checkbox_row("Delete all"))
    taken = look(ctx, SettleState.SETTLED)
    assert [(line.ref, line.role.value, line.name) for line in taken.lines] == [
        (ROW, "button", ""),
        (CHECKBOX, "checkbox", "Delete all"),
    ], "the printed snapshot is left alone"
    refused(act(ctx, click(taken, CHECKBOX)), ErrorCode.NOT_ACTIONABLE)
    outcome = act(ctx, click(taken, ROW))
    assert isinstance(outcome, Refused) and outcome.code is ErrorCode.COMMIT_REFUSED, (
        f"the touch lands on the row, and the checkbox in it says 'Delete all': {outcome}"
    )
    assert outcome.details["effects"] == ["delete"] and phone.permits == []


def test_a_deny_rule_reads_the_words_of_a_toggle_that_its_row_receives(tmp_path):
    j7 = merge((DEFAULT, load_profile(ROOT / "examples" / "devices" / "j7.toml").layer))
    ctx, phone = context(tmp_path, checkbox_row("Mobile data"), policy=j7)
    outcome = act(ctx, click(look(ctx, SettleState.SETTLED), ROW))
    assert isinstance(outcome, Refused) and outcome.code is ErrorCode.DENIED, (
        f"'mobile data' is on the element the tap toggles, and the J7 profile denies it: {outcome}"
    )
    assert phone.permits == []


def test_a_sideways_scroll_of_a_list_that_runs_down_is_refused(tmp_path):
    ctx, phone = context(tmp_path, SETTINGS)
    taken = look(ctx)
    for direction in (Direction.LEFT, Direction.RIGHT):
        sideways = refused(
            act(ctx, Request(Scroll(RefTarget(taken.ref(3)), direction))), ErrorCode.NOT_ACTIONABLE
        )
        assert sideways.details == {"reason": "wrong_axis"}
    assert phone.permits == []


def test_a_backend_that_fails_inside_inject_reports_the_input_as_uncertain(tmp_path):
    class Fails(FakePhone):
        def inject(self, permit):
            super().inject(permit)
            raise Refusal(ErrorCode.TRANSPORT, "adb timed out while it sent the tap")

    info = info_for(J7_SERIAL)
    phone = Fails(info, SETTINGS)
    ctx = Context(
        phone, info, None, POLICY, SnapshotStore(tmp_path), Ledger(tmp_path, info.identity), FakeClock()
    )
    done = act(ctx, click(look(ctx), DISPLAY_TILE))
    assert isinstance(done, Acted) and done.disposition is Disposition.DELIVERY_UNCERTAIN
    assert done.error is ErrorCode.TRANSPORT and ctx.ledger.epoch() == 1


def test_a_sideways_scroll_of_a_pager_or_of_rows_side_by_side_is_sent(tmp_path):
    carousel = window(
        node(
            "androidx.recyclerview.widget.RecyclerView",
            node("android.widget.Button", text="Card 1", clickable=True, bounds="[0,500][400,700]"),
            node("android.widget.Button", text="Card 2", clickable=True, bounds="[400,500][800,700]"),
            scrollable=True,
            bounds="[0,500][1080,700]",
        )
    )
    ctx, phone = context(tmp_path, carousel)
    done = act(ctx, Request(Scroll(RefTarget(look(ctx, SettleState.SETTLED).ref(1)), Direction.RIGHT)))
    assert isinstance(done, Acted) and isinstance(phone.permits[0].action, Swipe)


def test_a_blank_frame_between_two_screens_proves_nothing_gone(tmp_path):
    blank = window(node("android.widget.FrameLayout", bounds="[0,0][1080,1920]"))
    ctx, _ = context(tmp_path, SETTINGS, after_input=[blank, DISPLAY_PAGE])
    done = act(ctx, click(look(ctx), DISPLAY_TILE, wait_for=(Gone(Q("Display")),)))
    assert isinstance(done, Acted) and done.after is not None
    assert any("Brightness" in line.name for line in done.after.lines), "the wait stopped on the blank frame"
