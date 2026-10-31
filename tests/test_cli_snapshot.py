import pytest
from fakes import J7_SERIAL, FakeHub, invoke
from support import fixture_screen

from agent_phone.core.device import Connected

J7 = Connected(J7_SERIAL, "SM_J730F", ready=True)


def snapshot(argv, tmp_path, screens=("settings-home",)):
    hub = FakeHub([J7], screens=[fixture_screen(name) for name in screens])
    return invoke(["snapshot", *argv], hub, tmp_path)


def test_a_snapshot_with_no_flag_is_compact(tmp_path):
    code, wire = snapshot([], tmp_path)
    assert code == 0 and wire["data"]["mode"] == "compact"
    assert len(wire["data"]["tree"]) == 8


def test_skeleton_folds_the_rows_of_a_collection_and_says_how_many(tmp_path):
    code, wire = snapshot(["--skeleton"], tmp_path)
    assert code == 0 and wire["data"]["mode"] == "skeleton"
    assert wire["data"]["tree"][-1].endswith("list #dashboard_container (4 rows) (+4) [0,179,1920,1080]")


def test_full_prints_every_node_of_the_window(tmp_path):
    code, wire = snapshot(["--full"], tmp_path)
    assert code == 0 and wire["data"]["mode"] == "full" and len(wire["data"]["tree"]) == 50


@pytest.mark.parametrize("argv", [["--skeleton", "--full"], ["--compact", "--skeleton"], ["--tiny"]])
def test_two_modes_at_once_or_an_unknown_flag_is_invalid_args(tmp_path, argv):
    code, wire = snapshot(argv, tmp_path)
    assert code == 2 and wire["error"]["code"] == "INVALID_ARGS"
    assert (wire["delivery"], wire["retry"]) == ("not_delivered", "safe")
