import json

import pytest
from fakes import J7_SERIAL, FakeHub, invoke
from support import FakeClock, fixture_screen, node, screen_of

from agent_phone.cli.driver import PhoneError, open_phone
from agent_phone.cli.settings import Settings
from agent_phone.core.device import Connected
from agent_phone.core.query import Q
from agent_phone.core.refs.store import SnapshotStore
from agent_phone.core.snapshot.surface import Pick

J7 = Connected(J7_SERIAL, "SM_J730F", ready=True)


def find(argv, tmp_path, screen="settings-home", hub=None):
    hub = hub or FakeHub([J7], screens=[fixture_screen(screen) if isinstance(screen, str) else screen])
    code, wire = invoke(["find", *argv], hub, tmp_path)
    return code, wire


def test_a_name_finds_the_line_a_snapshot_prints_with_its_ref(tmp_path):
    code, wire = find(["--name", "connections"], tmp_path)
    data = wire["data"]
    assert code == 0 and data["count"] == 1 and data["truncated"] == 0
    tile = 'button "Connections" "Wi-Fi, Bluetooth, Data usage, Airplane m…" focused [0,179,1920,394]'
    assert data["matches"] == [f"@{data['id']}:e4 {tile}"]
    assert (data["app"], data["window"]) == ("com.android.settings", "application")


def test_every_match_is_listed_and_none_is_reduced_to_one(tmp_path):
    code, wire = find(["--id", "outer_container"], tmp_path, "ig-feed")
    data = wire["data"]
    assert data["count"] == 4 and len(data["matches"]) == 4 and data["truncated"] == 0
    assert [line.split()[0].split(":")[1] for line in data["matches"]] == ["e5", "e7", "e9", "e11"]


def test_a_limit_lists_fewer_and_the_count_and_truncated_say_what_is_left_out(tmp_path):
    code, wire = find(["--id", "outer_container", "--limit", "2"], tmp_path, "ig-feed")
    data = wire["data"]
    assert data["count"] == 4 and len(data["matches"]) == 2 and data["truncated"] == 2


def test_count_prints_only_the_count_and_records_nothing(tmp_path):
    code, wire = find(["--id", "outer_container", "--count"], tmp_path, "ig-feed")
    assert code == 0 and wire["data"] == {"count": 4}
    assert SnapshotStore(tmp_path).latest(J7_SERIAL) is None


def test_exact_compares_the_whole_name_and_the_default_compares_a_part(tmp_path):
    assert find(["--name", "connection"], tmp_path)[1]["data"]["count"] == 1
    assert find(["--name", "connection", "--exact"], tmp_path)[1]["data"]["count"] == 0
    assert find(["--name", "CONNECTIONS", "--exact"], tmp_path)[1]["data"]["count"] == 1


def test_text_finds_an_element_through_the_words_in_its_detail(tmp_path):
    data = find(["--text", "airplane"], tmp_path)[1]["data"]
    assert data["count"] == 1 and '"Connections"' in data["matches"][0]
    assert find(["--name", "airplane"], tmp_path)[1]["data"]["count"] == 0


def test_role_narrows_a_name(tmp_path):
    assert find(["--name", "settings", "--role", "text"], tmp_path)[1]["data"]["count"] == 1
    assert find(["--name", "settings", "--role", "button"], tmp_path)[1]["data"]["count"] == 0


def test_value_finds_a_field_by_what_was_typed(tmp_path):
    field = node("android.widget.EditText", text="lorenzo", hint="Name", clickable=True)
    screen = screen_of(node("android.widget.FrameLayout", field))
    code, wire = find(["--value", "lore", "--role", "field"], tmp_path, screen)
    assert code == 0 and wire["data"]["count"] == 1 and 'value="lorenzo"' in wire["data"]["matches"][0]


def test_finding_nothing_is_not_an_error(tmp_path):
    code, wire = find(["--name", "no such thing"], tmp_path)
    assert code == 0 and wire["ok"] is True
    assert (wire["data"]["count"], wire["data"]["matches"]) == (0, [])


def test_a_find_with_no_filter_is_invalid_args(tmp_path):
    code, wire = find([], tmp_path)
    assert (
        code == 2 and wire["error"]["code"] == "INVALID_ARGS" and "at least one" in wire["error"]["message"]
    )


@pytest.mark.parametrize(
    "argv", [["--role", "link"], ["--name", "x", "--limit", "0"], ["--name", "x", "--limit", "2", "--count"]]
)
def test_a_role_that_does_not_exist_a_zero_limit_or_a_limit_with_count_is_invalid_args(tmp_path, argv):
    assert find(argv, tmp_path)[0] == 2


def test_a_matched_ref_belongs_to_the_snapshot_the_find_recorded_and_can_be_drilled_into(tmp_path):
    hub = FakeHub([J7], screens=[fixture_screen("settings-home")])
    _, found = find(["--id", "dashboard_container"], tmp_path, hub=hub)
    ref = found["data"]["matches"][0].split()[0]
    assert ref.startswith(f"@{found['data']['id']}:e")
    code, drilled = invoke(["snapshot", "--root", ref], hub, tmp_path)
    assert code == 0 and len(drilled["data"]["tree"]) == 5


def test_a_root_limits_the_search_to_the_subtree_under_a_ref(tmp_path):
    hub = FakeHub([J7], screens=[fixture_screen("settings-home")])
    _, whole = invoke(["snapshot"], hub, tmp_path)
    ref = f"@{whole['data']['id']}:e3"
    assert find(["--role", "button"], tmp_path, hub=hub)[1]["data"]["count"] == 6
    assert find(["--role", "button", "--root", ref], tmp_path, hub=hub)[1]["data"]["count"] == 4


def test_the_surface_decides_which_window_is_searched(tmp_path):
    code, wire = find(["--text", "bluetooth", "--surface", "dialog"], tmp_path, "dialog-over-app")
    assert code == 0 and wire["data"]["count"] == 1
    code, wire = find(["--name", "ringer", "--surface", "all"], tmp_path, "dialog-over-app")
    assert code == 0 and wire["data"]["count"] == 1 and "Ringer vibrate." in wire["data"]["matches"][0]


def test_the_line_that_names_a_window_is_never_a_match(tmp_path):
    code, wire = find(["--name", "com.android", "--surface", "all"], tmp_path, "dialog-over-app")
    assert code == 0 and wire["data"]["count"] == 0
    code, wire = find(["--role", "group", "--surface", "all"], tmp_path, "dialog-over-app")
    assert all(not line.startswith('group "com.') for line in wire["data"]["matches"])


def test_a_surface_that_is_not_on_screen_is_no_surface(tmp_path):
    code, wire = find(["--name", "x", "--surface", "keyboard"], tmp_path, "ig-feed")
    assert code == 1 and wire["error"]["code"] == "NO_SURFACE"


def test_a_long_list_of_matches_is_cut_to_the_budget_and_says_how_many_were_left_out(tmp_path):
    rows = [
        node("android.widget.TextView", text=f"Message number {i} with a long preview", clickable=True)
        for i in range(300)
    ]
    screen = screen_of(node("android.widget.FrameLayout", *rows, bounds="[0,0][1080,1920]"))
    code, wire = find(["--name", "message", "--limit", "300"], tmp_path, screen)
    data = wire["data"]
    assert data["count"] == 300 and data["truncated"] > 0
    assert len(data["matches"]) + data["truncated"] == 300
    assert len(json.dumps(wire).encode()) < 8 * 1024


def test_the_driver_counts_and_lists_matches(tmp_path):
    hub = FakeHub([J7], screens=[fixture_screen("ig-feed")])
    settings = Settings(state_root=tmp_path, lock_wait_s=0.0)
    with open_phone(hub=hub, settings=settings, clock=FakeClock()) as phone:
        found = phone.find(Q(id="outer_container"), limit=3)
        assert (found.count, len(found.snapshot.lines), found.snapshot.truncated) == (4, 3, 1)
        assert phone.count(Q(id="outer_container")) == 4
        with pytest.raises(PhoneError):
            phone.find(Q("x"), pick=Pick.KEYBOARD)
