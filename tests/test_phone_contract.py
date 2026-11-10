"""What every `Phone` owes core, checked on each backend through the same tests. A new backend adds
a rig to `RIGS` and passes them."""

import pytest
from fakes import EMULATOR_SERIAL, J7_SERIAL, FakePhone, info_for
from support import fixture_screen

from agent_phone.core.act.ledger import Ledger
from agent_phone.core.outcome import ErrorCode
from agent_phone.core.phone import Key, KeyName, NotSent
from agent_phone.core.policy.engine import Clear, ClearReason, Grant

INFO = info_for(J7_SERIAL)
ELSEWHERE = info_for(EMULATOR_SERIAL).identity
SETTINGS = fixture_screen("settings-home")


def permit(root, action, device=INFO.identity):
    return Ledger(root, device).spend(action, Clear(ClearReason.NO_COMMIT_WORDS), Grant.none())


@pytest.mark.xfail(strict=True, reason="FakePhone.inject ignores the device its permit was made for")
def test_the_fake_phone_refuses_a_permit_for_another_device(tmp_path):
    phone = FakePhone(INFO, SETTINGS, after_input=[fixture_screen("dialog-over-app")])
    delivery = phone.inject(permit(tmp_path, Key(KeyName.BACK), ELSEWHERE))
    assert isinstance(delivery, NotSent) and delivery.code is ErrorCode.WRONG_DEVICE
    assert phone.permits == [] and phone.read() == SETTINGS
