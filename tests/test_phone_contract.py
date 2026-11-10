"""What every `Phone` owes core, checked on each backend through the same tests. A new backend adds
a rig to `RIGS` and passes them.

A rig builds the backend over a fake transport and counts the inputs that left for the device, so
"sent once" and "sent nothing" are observations. The transport answers every request, or with
`lost` it takes each input and never answers. How any other failure maps to a `Delivery` is each
adapter's own table (`tests/test_u2_inject.py`)."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import get_args

import pytest
from fakes import EMULATOR_SERIAL, J7_SERIAL, FakePhone, info_for
from support import FIXTURES, FakeClock, fixture_screen, fixture_xml
from test_u2_phone import IDLE_LIMIT_S, Forward, Server, Shell, answered

from agent_phone.adapters.uiautomator2.phone import DUMP_METHOD, U2Phone
from agent_phone.adapters.uiautomator2.rpc import Phase, RpcResult
from agent_phone.core.act.capability import required
from agent_phone.core.act.ledger import Ledger
from agent_phone.core.device import Package, Power
from agent_phone.core.geometry import Point, Rect
from agent_phone.core.outcome import ErrorCode
from agent_phone.core.phone import (
    Ack,
    Activate,
    InputAction,
    Key,
    KeyName,
    Launch,
    LongPress,
    NodeAddress,
    NotSent,
    OpenUri,
    Orientation,
    Phone,
    Rotate,
    Sent,
    SetClipboard,
    SetPower,
    SetText,
    Stop,
    Swipe,
    Tap,
)
from agent_phone.core.policy.engine import Clear, ClearReason, Grant

INFO = info_for(J7_SERIAL)
ELSEWHERE = info_for(EMULATOR_SERIAL).identity
SETTINGS = fixture_screen("settings-home")
APP = Package("com.android.settings")
FIELD = NodeAddress(
    APP,
    "android.widget.EditText",
    "android:id/search_src_text",
    "",
    "",
    Rect(150, 70, 900, 180),
    (0, 1),
    None,
)
FIELD_BOUNDS = {"left": 150, "top": 70, "right": 900, "bottom": 180}
INPUTS: tuple[InputAction, ...] = (
    Tap(Point(540, 300), FIELD),
    LongPress(Point(540, 300), FIELD, 800),
    Activate(FIELD),
    Swipe(Point(540, 1500), Point(540, 500), 275),
    SetText(FIELD, "display", False),
    *(Key(key) for key in KeyName),
    Launch(APP),
    Stop(APP),
    OpenUri("https://example.com", None),
    OpenUri("intent:#Intent;action=android.settings.SETTINGS;end", None),
    Rotate(Orientation.AUTO),
    SetPower(Power.ON),
    SetClipboard("copied"),
)


@dataclass(frozen=True, slots=True)
class Rig:
    phone: Phone
    sends: Callable[[], int]


def fake_rig(fixture: str, lost: bool = False) -> Rig:
    delivery = Sent(Ack.UNACKNOWLEDGED, "no answer") if lost else None
    phone = FakePhone(INFO, fixture_screen(fixture), delivery=delivery)
    return Rig(phone, lambda: len(phone.permits))


class ServerRpc:
    """A uiautomator2 server that shows `fixture`, finds the one field `FIELD` names, and answers
    every input, or with `lost` takes each input and never answers."""

    READS = {DUMP_METHOD: None, "count": 1, "objInfo": {"bounds": FIELD_BOUNDS}}

    def __init__(self, fixture: str, lost: bool) -> None:
        self.inputs: list[str] = []
        self._replies = self.READS | {DUMP_METHOD: fixture_xml(fixture)}
        self._lost = lost

    def call(self, method, params):
        if method in self._replies:
            return answered(self._replies[method])
        self.inputs.append(method)
        return RpcResult(Phase.WRITTEN, None, None) if self._lost else answered(True)


def u2_rig(fixture: str, lost: bool = False) -> Rig:
    rpc, shell = ServerRpc(fixture, lost), Shell()
    phone = U2Phone(INFO, rpc, Forward(), Server(), IDLE_LIMIT_S, FakeClock(), shell)
    return Rig(phone, lambda: len(rpc.inputs) + len(shell.ran))


RIGS = {"fake": fake_rig, "uiautomator2": u2_rig}


@pytest.fixture(params=RIGS)
def rig_for(request) -> Callable[..., Rig]:
    return RIGS[request.param]


def permit(root, action, device=INFO.identity):
    return Ledger(root, device).spend(action, Clear(ClearReason.NO_COMMIT_WORDS), Grant.none())


def test_the_fake_phone_refuses_a_permit_for_another_device(tmp_path):
    phone = FakePhone(INFO, SETTINGS, after_input=[fixture_screen("dialog-over-app")])
    delivery = phone.inject(permit(tmp_path, Key(KeyName.BACK), ELSEWHERE))
    assert isinstance(delivery, NotSent) and delivery.code is ErrorCode.WRONG_DEVICE
    assert phone.permits == [] and phone.read() == SETTINGS


def test_the_inputs_above_name_every_kind_of_input():
    assert {type(action) for action in INPUTS} == set(get_args(InputAction)), (
        "a new kind of input needs a row in INPUTS, so that every backend is asked to deliver it"
    )


@pytest.mark.parametrize("action", INPUTS, ids=lambda action: type(action).__name__)
def test_a_permit_is_sent_once_or_is_proven_unsent(rig_for, tmp_path, action):
    rig = rig_for("settings-home")
    delivery = rig.phone.inject(permit(tmp_path, action))
    assert isinstance(delivery, Sent | NotSent), "every kind of input gets an answer, never None"
    assert rig.sends() == (1 if isinstance(delivery, Sent) else 0)
    if required(action) in (None, *rig.phone.info().capabilities):
        assert isinstance(delivery, Sent), "a backend delivers every input it declares it can do"


@pytest.mark.parametrize("action", INPUTS, ids=lambda action: type(action).__name__)
def test_an_input_that_left_and_got_no_answer_is_never_reported_unsent(rig_for, tmp_path, action):
    rig = rig_for("settings-home", lost=True)
    delivery = rig.phone.inject(permit(tmp_path, action))
    assert rig.sends() == 0 or isinstance(delivery, Sent), "a refund here would revive spent refs"


@pytest.mark.parametrize("action", INPUTS, ids=lambda action: type(action).__name__)
def test_a_permit_for_another_device_sends_nothing(rig_for, tmp_path, action):
    rig = rig_for("settings-home")
    delivery = rig.phone.inject(permit(tmp_path, action, ELSEWHERE))
    assert isinstance(delivery, NotSent) and delivery.code is ErrorCode.WRONG_DEVICE
    assert rig.sends() == 0


@pytest.mark.parametrize("fixture", FIXTURES)
def test_a_read_shows_at_most_one_active_window_and_sends_nothing(rig_for, fixture):
    rig = rig_for(fixture)
    assert sum(window.active for window in rig.phone.read().windows) <= 1
    assert rig.sends() == 0
