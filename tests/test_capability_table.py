"""One table says what each input needs from a backend. act() asks it before the first read for an
input with no target, and always before the spend, so a refused input costs the agent no ref."""

from typing import get_args

import pytest
from fakes import J7_SERIAL, FakeHub, info_for, invoke
from test_act import DISPLAY_TILE, SETTINGS, click, context, look, refused
from test_facts import RECORDED, ScriptedAdb
from test_u2_phone import phone_with

from agent_phone.adapters.uiautomator2.phone import U2Hub
from agent_phone.core.act.act import act
from agent_phone.core.act.capability import required
from agent_phone.core.act.intent import Request
from agent_phone.core.device import Capability, Connected, Package, Power
from agent_phone.core.geometry import Point, Rect
from agent_phone.core.outcome import Acted, ErrorCode
from agent_phone.core.phone import (
    Activate,
    InputAction,
    Key,
    KeyName,
    Launch,
    LongPress,
    NodeAddress,
    OpenUri,
    Orientation,
    Rotate,
    SetClipboard,
    SetPower,
    SetText,
    Stop,
    Swipe,
    Tap,
)
from agent_phone.core.query import Q
from agent_phone.core.wait.predicate import Gone

NODE = NodeAddress(Package("a.b"), "", "", "", "", Rect(0, 0, 1, 1), (), None)
INTENT = "intent:#Intent;action=android.settings.SETTINGS;end"
NEEDS = [
    (Tap(Point(0, 0), NODE), "point_input"),
    (LongPress(Point(0, 0), NODE, 800), "point_input"),
    (Swipe(Point(0, 0), Point(0, 1), 275), "point_input"),
    (Activate(NODE), "semantic_click"),
    (Key(KeyName.BACK), "key_back"),
    (Key(KeyName.RECENTS), "key_recents"),
    (Key(KeyName.HOME), None),
    (Key(KeyName.ENTER), None),
    (OpenUri(INTENT, None), "intent_links"),
    (OpenUri(INTENT.upper(), None), "intent_links"),
    (OpenUri("https://example.com", None), None),
    (Rotate(Orientation.AUTO), "rotate"),
    (SetPower(Power.ON), "power"),
    (SetClipboard("x"), "clipboard"),
    (SetText(NODE, "x", False), None),
    (Launch(Package("a.b")), None),
    (Stop(Package("a.b")), None),
]
U2_HAS = {
    "point_input",
    "key_back",
    "key_recents",
    "intent_links",
    "rotate",
    "power",
    "clipboard",
    "screenshot",
}


def info_without(name):
    return info_for(J7_SERIAL, capabilities=info_for(J7_SERIAL).capabilities - {Capability(name)})


def test_every_input_action_has_a_capability_row():
    assert {type(action) for action, _ in NEEDS} == set(get_args(InputAction)), (
        "a new kind of input needs a row here and a case in required()"
    )
    for action, name in NEEDS:
        need = required(action)
        assert (need and need.value) == name, action
    assert {action.key for action, _ in NEEDS if isinstance(action, Key)} == set(KeyName), (
        "a new key needs a row here and a case in required()"
    )
    with pytest.raises(AssertionError):
        required(object())


def test_a_key_the_backend_lacks_is_refused_before_any_read(tmp_path):
    ctx, phone = context(tmp_path, SETTINGS, info=info_without("key_back"))
    taken = look(ctx)
    reads = phone.reads
    back = Request(Key(KeyName.BACK), wait_for=(Gone(Q("Display")),))
    outcome = refused(act(ctx, back), ErrorCode.NOT_SUPPORTED)
    assert outcome.details == {"capability": "key_back"}
    assert phone.reads == reads and ctx.ledger.epoch() == 0 and phone.permits == []
    assert isinstance(act(ctx, click(taken, DISPLAY_TILE)), Acted), "the refusal spent no ref"


def test_a_key_the_backend_lacks_is_refused_before_the_agent_is_told_to_look_first(tmp_path):
    ctx, phone = context(tmp_path, SETTINGS, info=info_without("key_back"))
    refused(act(ctx, Request(Key(KeyName.BACK))), ErrorCode.NOT_SUPPORTED)
    assert phone.reads == 0 and phone.permits == []


def test_an_intent_link_needs_intent_links_and_a_web_link_does_not(tmp_path):
    ctx, phone = context(tmp_path, SETTINGS, info=info_without("intent_links"))
    look(ctx)
    refused(act(ctx, Request(OpenUri(INTENT, None))), ErrorCode.NOT_SUPPORTED)
    assert phone.permits == [] and ctx.ledger.epoch() == 0
    assert isinstance(act(ctx, Request(OpenUri("https://example.com", None))), Acted)
    assert len(phone.permits) == 1


def test_the_uiautomator2_backend_declares_what_it_has_before_and_after_it_opens_a_phone():
    listed = U2Hub(ScriptedAdb(RECORDED)).inspect(J7_SERIAL)
    assert {c.value for c in listed.capabilities} == U2_HAS
    assert phone_with(None).info().capabilities == listed.capabilities


def test_devices_prints_the_capabilities_of_a_device_whose_facts_it_read():
    _, wire = invoke(["devices"], FakeHub([Connected(J7_SERIAL, "SM_J730F", ready=True)]))
    assert wire["data"]["devices"][0]["capabilities"] == sorted(U2_HAS), "the fake declares what u2 does"
