"""`scroll <direction> <list> --until QUERY`: swipe the list until a line that matches shows, in one
call. Each swipe is its own gated input, and the result is the last one, with the screen it ended on."""

from fakes import J7_SERIAL, FakeHub, invoke
from support import node, screen_of

from agent_phone.core.device import Connected

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
