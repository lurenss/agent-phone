"""`scroll <direction> <list> --until QUERY`: swipe the list until a line that matches shows, in one
call. Each swipe is its own gated input, and the result is the last one, with the screen it ended on."""

import pytest
from fakes import J7_SERIAL, FakeHub, FakePhone, invoke
from support import node, screen_of

from agent_phone.cli.driver import PhoneError, open_phone
from agent_phone.cli.settings import Settings
from agent_phone.core.act.intent import Direction
from agent_phone.core.device import Connected
from agent_phone.core.phone import Ack, Sent
from agent_phone.core.query import Query
from agent_phone.core.refs.resolve import RefTarget
from agent_phone.core.snapshot.snapshot import RefToken
from agent_phone.core.wait.clock import POLL_GAP_S
from agent_phone.core.wait.observe import SETTLE_QUIET_S
from agent_phone.core.wait.predicate import Present

J7 = Connected(J7_SERIAL, "SM_J730F", ready=True)


def page(*names):
    rows = [
        node(
            "android.widget.Button",
            text=name,
            clickable=True,
            bounds=f"[0,{at * 300}][1080,{at * 300 + 300}]",
        )
        for at, name in enumerate(names)
    ]
    return screen_of(
        node(
            "android.widget.FrameLayout",
            node(
                "androidx.recyclerview.widget.RecyclerView",
                *rows,
                resource_id="com.android.settings:id/main_list",
                scrollable=True,
                bounds="[0,0][1080,1920]",
            ),
            package="com.android.settings",
            bounds="[0,0][1080,1920]",
        )
    )


TOP = page("Network", "Apps", "Battery")
MIDDLE = page("Battery", "Display", "Storage")
BOTTOM = page("Storage", "System", "About phone")
SCROLL = ["scroll", "down", "id=main_list", "--until", "name=About phone"]


def looked(root):
    code, _ = invoke(["snapshot"], FakeHub([J7], screens=[TOP]), root)
    assert code == 0


def test_until_swipes_until_the_line_shows_and_returns_that_screen(tmp_path):
    looked(tmp_path)
    hub = FakeHub([J7], screens=[TOP], after_each=[MIDDLE, BOTTOM])
    code, wire = invoke(SCROLL, hub, tmp_path)
    assert code == 0 and wire["ok"] and len(hub.phones[0].permits) == 2, "two swipes, each a gated input"
    assert wire["data"]["input"]["kind"] == "swipe" and wire["data"]["input"]["times"] == 2
    after = wire["data"]["after"]
    assert after["settled"] == "settled" and any('"About phone"' in line for line in after["tree"])
    ref = next(line.split()[0] for line in after["tree"] if '"About phone"' in line)
    code, wire = invoke(["click", ref], FakeHub([J7], screens=[BOTTOM]), tmp_path)
    assert code == 0 and wire["data"]["target"]["name"] == "About phone"


def test_until_stops_when_the_list_stops_moving(tmp_path):
    looked(tmp_path)
    hub = FakeHub([J7], screens=[TOP], after_each=[MIDDLE, MIDDLE])
    code, wire = invoke(SCROLL, hub, tmp_path)
    assert code == 1 and wire["error"]["code"] == "NOT_FOUND" and len(hub.phones[0].permits) == 2
    assert wire["delivery"] == "delivered_unverified" and wire["retry"] == "unsafe"
    assert any('"Display"' in line for line in wire["data"]["after"]["tree"]), "the screen it stopped on"


def test_until_sends_nothing_when_the_line_already_shows(tmp_path):
    looked(tmp_path)
    hub = FakeHub([J7], screens=[TOP], after_each=[MIDDLE])
    code, wire = invoke(["scroll", "down", "id=main_list", "--until", "name=Apps"], hub, tmp_path)
    assert code == 2 and wire["error"]["code"] == "INVALID_ARGS" and wire["delivery"] == "not_delivered"
    assert hub.phones[0].permits == []


def test_until_takes_a_query_for_the_list_and_not_a_ref(tmp_path):
    hub = FakeHub([J7], screens=[TOP])
    code, wire = invoke(["scroll", "down", "@abcde:e1", "--until", "name=About phone"], hub, tmp_path)
    assert code == 2 and wire["error"]["code"] == "INVALID_ARGS" and hub.phones == []
    assert "query" in wire["error"]["message"], "a ref is spent by the first swipe"


def test_until_gives_up_after_its_swipes_and_says_how_many(tmp_path):
    looked(tmp_path)
    endless = [page(f"Row {n}", f"Row {n + 1}", f"Row {n + 2}") for n in range(1, 40)]
    hub = FakeHub([J7], screens=[TOP], after_each=endless)
    code, wire = invoke(SCROLL, hub, tmp_path)
    assert code == 1 and wire["error"]["code"] == "NOT_FOUND"
    assert len(hub.phones[0].permits) == 10 and "10 swipes" in wire["error"]["message"]


def test_until_takes_no_wait_for_and_ignores_a_settle_beside_it(tmp_path):
    looked(tmp_path)
    hub = FakeHub([J7], screens=[TOP], after_each=[MIDDLE, BOTTOM])
    code, wire = invoke([*SCROLL, "--wait-for", "name=System"], hub, tmp_path)
    assert code == 2 and wire["error"]["code"] == "INVALID_ARGS" and hub.phones == []
    code, wire = invoke([*SCROLL, "--settle"], hub, tmp_path)
    assert code == 0 and len(hub.phones[0].permits) == 2


def test_until_with_after_diff_compares_with_the_screen_the_caller_stood_on(tmp_path):
    start = page("Network", "Apps", "Battery", "Display", "Sound")
    code, _ = invoke(["snapshot"], FakeHub([J7], screens=[start]), tmp_path)
    moved = [
        page("Apps", "Battery", "Display", "Sound", "Storage"),
        page("Battery", "Display", "Sound", "Storage", "About phone"),
    ]
    hub = FakeHub([J7], screens=[start], after_each=moved)
    _, wire = invoke([*SCROLL, "--after", "diff"], hub, tmp_path)
    after = wire["data"]["after"]
    assert len(hub.phones[0].permits) == 2 and after["kept"] == 4
    assert after["gone"] == ['button "Network"', 'button "Apps"'], "not the lines of the screen between"
    assert [line.split(" ", 1)[1].rsplit(" [", 1)[0] for line in after["added"]] == [
        'button "Storage"',
        'button "About phone"',
    ]


def two_lists():
    lists = [
        node("android.widget.ListView", scrollable=True, bounds=f"[0,{top}][1080,{top + 900}]")
        for top in (0, 900)
    ]
    return screen_of(node("android.widget.FrameLayout", *lists, bounds="[0,0][1080,1920]"))


def test_a_swipe_refused_after_one_went_out_keeps_its_details_and_the_delivery(tmp_path):
    looked(tmp_path)
    hub = FakeHub([J7], screens=[TOP], after_each=[two_lists()])
    code, wire = invoke(["scroll", "down", "--until", "name=About phone"], hub, tmp_path)
    assert code == 1 and wire["error"]["code"] == "AMBIGUOUS_TARGET"
    assert wire["error"]["details"] == {"matches": 2}, "what the refusal said is not lost"
    assert wire["delivery"] == "delivered_unverified" and len(hub.phones[0].permits) == 1
    assert "times" not in wire["data"]["input"], "one swipe went out"


class Restless(FakePhone):
    """After an input, every read shows another screen than the read before it."""

    def read(self):
        if not self.permits:
            return super().read()
        self.reads += 1
        return page("Battery", "Display", f"frame {self.reads}")


class LateRow(FakePhone):
    """After an input the screen stands still for a settle, and one read later a row has loaded."""

    def read(self):
        if not self.permits:
            return super().read()
        self.late = getattr(self, "late", 0) + 1
        return BOTTOM if self.late > int(SETTLE_QUIET_S / POLL_GAP_S) + 1 else MIDDLE


def hub_of(phone_class):
    class Hub(FakeHub):
        def open(self, serial, first_read=False):
            self.phones.append(phone_class(self._infos[serial], *self._screens))
            return self.phones[-1]

    return Hub([J7], screens=[TOP])


def test_until_stops_after_one_swipe_on_a_screen_that_does_not_settle(tmp_path):
    looked(tmp_path)
    hub = hub_of(Restless)
    code, wire = invoke([*SCROLL, "--timeout-ms", "1500"], hub, tmp_path)
    assert code == 1 and wire["error"]["code"] == "NOT_FOUND" and len(hub.phones[0].permits) == 1
    assert "did not settle" in wire["error"]["message"] and wire["data"]["after"]["settled"] == "unsettled"


def test_the_screen_until_returns_prints_the_line_also_when_it_loaded_after_the_settle(tmp_path):
    looked(tmp_path)
    hub = hub_of(LateRow)
    code, wire = invoke(SCROLL, hub, tmp_path)
    after = wire["data"]["after"]
    assert code == 0 and len(hub.phones[0].permits) == 1
    assert any('"About phone"' in line for line in after["tree"]) and after["settled"] == "unchecked"


def test_until_reports_the_weakest_delivery_of_its_swipes(tmp_path):
    looked(tmp_path)
    unacknowledged = Sent(Ack.UNACKNOWLEDGED, "fake")
    hub = FakeHub([J7], screens=[TOP], after_each=[MIDDLE, BOTTOM], delivery=unacknowledged)
    code, wire = invoke(SCROLL, hub, tmp_path)
    assert code == 0 and wire["delivery"] == "delivery_uncertain" and wire["retry"] == "unsafe"


def test_the_driver_holds_until_to_the_same_rules_as_the_command_line(tmp_path):
    settings = Settings(state_root=tmp_path, lock_wait_s=0.0)
    hub = FakeHub([J7], screens=[TOP], after_each=[MIDDLE, BOTTOM])
    about, lists = Query(name="About phone"), Query(resource_id="main_list")
    with open_phone(hub=hub, settings=settings) as phone:
        taken = phone.snapshot()
        ref = RefTarget(RefToken.parse(f"@{taken.id}:e1"))
        for target, wait_for in ((ref, ()), (lists, Present(Query(name="System")))):
            with pytest.raises(PhoneError) as raised:
                phone.scroll(Direction.DOWN, target, wait_for=wait_for, until=about)
            assert raised.value.outcome.code.value == "INVALID_ARGS" and hub.phones[0].permits == []
        acted = phone.scroll(Direction.DOWN, lists, until=about)
    assert acted.inputs == 2 and acted.error is None
