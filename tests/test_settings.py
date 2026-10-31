from pathlib import Path

from agent_phone.cli.settings import Settings


def test_state_root_defaults_to_the_home_folder_when_the_variable_is_unset():
    assert Settings.from_environment({}).state_root == Path.home() / ".agent-phone"


def test_state_root_follows_the_variable(tmp_path):
    assert Settings.from_environment({"AGENT_PHONE_HOME": str(tmp_path)}).state_root == tmp_path
