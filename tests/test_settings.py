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


def test_no_phone_host_is_named_unless_the_variable_names_one():
    assert Settings.from_environment({}).remote is None
    assert Settings.from_environment({"AGENT_PHONE_REMOTE": ""}).remote is None


@pytest.mark.parametrize("alias", ["farm", "pi-2", "phones@farm.example", "farm_1"])
def test_the_phone_host_is_the_ssh_alias_in_the_variable(alias):
    assert Settings.from_environment({"AGENT_PHONE_REMOTE": alias}).remote == alias


@pytest.mark.parametrize("alias", ["-oProxyCommand=id", "two words", "a/b", "../farm", "farm;id", "farm\n"])
def test_an_alias_that_ssh_or_a_file_name_could_read_as_something_else_is_refused(alias):
    with pytest.raises(Refusal) as refused:
        Settings.from_environment({"AGENT_PHONE_REMOTE": alias})
    assert refused.value.code is ErrorCode.INVALID_ARGS and "AGENT_PHONE_REMOTE" in refused.value.message


def test_the_task_is_what_the_variable_says_and_nothing_when_it_is_unset_or_empty():
    assert Settings.from_environment({"AGENT_PHONE_TASK": "schedule reel 12"}).task == "schedule reel 12"
    assert Settings.from_environment({}).task is None
    assert Settings.from_environment({"AGENT_PHONE_TASK": ""}).task is None


@pytest.mark.parametrize("task", ["x" * 81, "clear\x1b[2J", "two\nlines"])
def test_a_task_other_people_could_not_read_on_one_line_is_refused(task):
    with pytest.raises(Refusal) as refused:
        Settings.from_environment({"AGENT_PHONE_TASK": task})
    assert refused.value.code is ErrorCode.INVALID_ARGS and "AGENT_PHONE_TASK" in refused.value.message
