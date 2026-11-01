"""click, set-text and scroll take a ref or a query on the command line. A query is found again on
the live screen and must match one element, and it needs a current observation as a ref does. Each
case checks what reached the fake device, so "sends nothing" is an observation."""

import re

import pytest
from fakes import J7_SERIAL, FakeHub, invoke
from support import fixture_screen, node, screen_of

from agent_phone.core.device import Connected
from agent_phone.core.phone import Swipe, Tap

J7 = Connected(J7_SERIAL, "SM_J730F", ready=True)
SETTINGS = fixture_screen("settings-home")
BRIGHTNESS = screen_of(
    node(
        "android.widget.FrameLayout",
        node("android.widget.TextView", text="Brightness", bounds="[0,200][1080,300]"),
        package="com.android.settings",
        bounds="[0,0][1080,1920]",
    )
)
NO_CANDIDATES = pytest.mark.xfail(
    strict=True, reason="the hint names details.candidates, which a query refusal never carries"
)


def search(text=""):
    return screen_of(
        node(
            "android.widget.FrameLayout",
            node(
                "android.widget.EditText",
                text=text,
                hint="Search",
                clickable=True,
                bounds="[0,100][1080,200]",
            ),
            package="com.android.settings",
            bounds="[0,0][1080,1920]",
        )
    )


def snapshot(root, screen=SETTINGS):
    code, wire = invoke(["snapshot"], FakeHub([J7], screens=[screen]), root)
    assert code == 0
    return wire["data"]["id"]


def sent(hub):
    return [permit.action for phone in hub.phones for permit in phone.permits]


def test_a_query_taps_the_one_element_it_matches_where_its_ref_would(tmp_path):
    by_ref, by_query = tmp_path / "ref", tmp_path / "query"
    taken = snapshot(by_ref)
    snapshot(by_query)
    wait = ["--wait-for", "name=Brightness"]
    code, tapped = invoke(
        ["click", f"@{taken}:e7", *wait], FakeHub([J7], screens=[SETTINGS], after_input=[BRIGHTNESS]), by_ref
    )
    assert code == 0 and tapped["data"]["target"]["ref"] == f"@{taken}:e7"
    hub = FakeHub([J7], screens=[SETTINGS], after_input=[BRIGHTNESS])
    code, wire = invoke(["click", "name=Display", *wait], hub, by_query)
    assert code == 0 and wire["delivery"] == "delivered_verified"
    assert wire["data"]["target"] == {**tapped["data"]["target"], "ref": None}
    assert wire["data"]["input"] == tapped["data"]["input"]
    assert [type(action) for action in sent(hub)] == [Tap]


def test_a_query_that_matches_two_elements_is_ambiguous_and_sends_nothing(tmp_path):
    snapshot(tmp_path)
    hub = FakeHub([J7], screens=[SETTINGS])
    code, wire = invoke(["click", "role=button"], hub, tmp_path)
    assert code == 1 and wire["error"]["code"] == "AMBIGUOUS_TARGET"
    assert (wire["delivery"], wire["retry"]) == ("not_delivered", "safe")
    assert wire["error"]["details"]["matches"] > 1 and sent(hub) == []


def test_a_query_with_no_observation_is_refused_before_the_screen_is_read(tmp_path):
    hub = FakeHub([J7], screens=[SETTINGS])
    code, wire = invoke(["click", "name=Display"], hub, tmp_path)
    assert code == 1 and wire["error"]["code"] == "OBSERVE_FIRST" and wire["retry"] == "safe"
    assert hub.phones[0].reads == 0 and sent(hub) == []


def test_a_query_after_an_input_needs_a_new_observation(tmp_path):
    taken = snapshot(tmp_path)
    hub = FakeHub([J7], screens=[SETTINGS], after_input=[BRIGHTNESS])
    code, _ = invoke(["click", f"@{taken}:e7"], hub, tmp_path)
    assert code == 0
    again = FakeHub([J7], screens=[SETTINGS])
    code, wire = invoke(["click", "name=Display"], again, tmp_path)
    assert code == 1 and wire["error"]["code"] == "OBSERVE_FIRST" and wire["retry"] == "safe"
    assert sent(again) == [] and again.phones[0].reads == 0
    snapshot(tmp_path)
    code, wire = invoke(["click", "name=Display"], FakeHub([J7], screens=[SETTINGS]), tmp_path)
    assert code == 0 and wire["data"]["target"]["name"] == "Display"


def test_set_text_and_scroll_find_their_element_by_query(tmp_path):
    snapshot(tmp_path, search())
    hub = FakeHub([J7], screens=[search()], after_input=[search("display")])
    code, wire = invoke(["set-text", "role=field", "display"], hub, tmp_path)
    assert code == 0 and wire["delivery"] == "delivered_verified"
    assert wire["data"]["target"]["ref"] is None and wire["data"]["target"]["role"] == "field"
    snapshot(tmp_path)
    hub = FakeHub([J7], screens=[SETTINGS])
    code, wire = invoke(["scroll", "down", "role=list"], hub, tmp_path)
    assert code == 0 and wire["data"]["target"]["role"] == "list"
    assert [type(action) for action in sent(hub)] == [Swipe]


def test_a_target_that_is_neither_a_ref_nor_a_query_is_refused_before_any_device_is_opened(tmp_path):
    snapshot(tmp_path)
    for argv in (
        ["click", "e7"],
        ["click", "Display"],
        ["click", "@e7"],
        ["click", "name="],
        ["click", "name=Display name=Other"],
        ["scroll", "down", "Display"],
        ["set-text", "display"],
    ):
        hub = FakeHub([J7], screens=[SETTINGS])
        code, wire = invoke(argv, hub, tmp_path)
        assert code == 2 and wire["error"]["code"] == "INVALID_ARGS" and hub.phones == [], argv


@NO_CANDIDATES
def test_an_ambiguous_target_hint_names_only_details_the_error_carries(tmp_path):
    snapshot(tmp_path)
    code, wire = invoke(["click", "role=button"], FakeHub([J7], screens=[SETTINGS]), tmp_path)
    error = wire["error"]
    assert code == 1 and error["hint"]
    for key in re.findall(r"details\.(\w+)", error["hint"]):
        assert key in error["details"], f"the hint sends the agent to details.{key}, which is not there"
