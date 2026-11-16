import pytest
from support import FakeClock

from agent_phone.cli.hub import open_hub
from agent_phone.cli.settings import Settings
from agent_phone.core.outcome import ErrorCode, Refusal


def test_with_no_phone_host_named_the_hub_is_this_computers_adb():
    with open_hub(Settings(adb="false"), FakeClock(), task="t", linger=False) as hub:
        with pytest.raises(Refusal) as refused:
            hub.connected()
    assert refused.value.code is ErrorCode.TRANSPORT and "adb devices failed" in refused.value.message
