from pathlib import Path

import pytest

from agent_phone.cli.settings import Settings
from agent_phone.core.outcome import ErrorCode, Refusal
from agent_phone.core.policy.mode import PermissionMode


def test_state_root_defaults_to_the_home_folder_when_the_variable_is_unset():
    assert Settings.from_environment({}).state_root == Path.home() / ".agent-phone"


def test_state_root_follows_the_variable(tmp_path):
    assert Settings.from_environment({"AGENT_PHONE_HOME": str(tmp_path)}).state_root == tmp_path


def test_the_permission_mode_is_ask_when_the_variable_is_unset_or_empty():
    assert Settings.from_environment({}).permission_mode is PermissionMode.ASK
    assert (
        Settings.from_environment({"AGENT_PHONE_PERMISSION_MODE": ""}).permission_mode is PermissionMode.ASK
    )


@pytest.mark.parametrize("mode", PermissionMode)
def test_the_permission_mode_follows_the_variable(mode):
    assert Settings.from_environment({"AGENT_PHONE_PERMISSION_MODE": mode.value}).permission_mode is mode


def test_a_permission_mode_that_does_not_exist_is_refused_with_the_two_that_do():
    with pytest.raises(Refusal) as refused:
        Settings.from_environment({"AGENT_PHONE_PERMISSION_MODE": "skip"})
    assert refused.value.code is ErrorCode.INVALID_ARGS
    assert all(mode.value in refused.value.message for mode in PermissionMode)


def test_no_other_variable_changes_the_permission_mode():
    env = {"AGENT_PHONE_HOME": "/tmp/x", "AGENT_PHONE_IDLE_S": "5", "ADB": "adb", "PERMISSION_MODE": "x"}
    assert Settings.from_environment(env).permission_mode is PermissionMode.ASK
