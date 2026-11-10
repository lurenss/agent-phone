"""Every command that reads or drives a phone leaves two lines in that phone's trace of the day: a
begin line before it runs and an end line after. `flow record` drafts a flow from them, and a
begin line with no end line shows a command that died on the way."""

import json
import os
import re
import stat

import pytest
from fakes import J7_SERIAL, FakeHub, FakePhone, invoke
from support import fixture_screen, node, screen_of

from agent_phone.core.device import Connected

todo = pytest.mark.xfail(strict=True, reason="the trace of single commands is not written yet")

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
SEARCH = screen_of(
    node(
        "android.widget.FrameLayout",
        node(
            "android.widget.EditText",
            text="Search settings",
            resource_id="com.android.settings:id/search",
            clickable=True,
            bounds="[0,200][1080,300]",
        ),
        package="com.android.settings",
        bounds="[0,0][1080,1920]",
    )
)


def hub(screen=SETTINGS, after=BRIGHTNESS):
    return FakeHub([J7], screens=[screen], after_input=[after])


def trace_file(root):
    [path] = [p for p in (root / "traces" / J7_SERIAL).iterdir() if not p.name.endswith("-batch.jsonl")]
    return path


def lines(root):
    return [json.loads(line) for line in trace_file(root).read_text().splitlines()]


def mode(path):
    return stat.S_IMODE(os.stat(path).st_mode)


@todo
def test_a_single_click_leaves_a_begin_and_an_end_line(tmp_path):
    phone = hub()
    _, taken = invoke(["snapshot"], phone, tmp_path)
    ref = next(line.split()[0] for line in taken["data"]["tree"] if '"Display"' in line)
    code, wire = invoke(["click", ref, "--wait-for", "name=Brightness"], phone, tmp_path)
    assert code == 0
    looked, looked_end, begin, end = lines(tmp_path)
    assert (looked["line"], looked["seq"], looked["command"]) == ("begin", 0, "snapshot")
    assert (looked_end["line"], looked_end["seq"], looked_end["ok"]) == ("end", 0, True)
    assert begin["line"] == "begin" and begin["seq"] == 1 and begin["command"] == "click"
    assert begin["argv"] == ["click", ref, "--wait-for", "name=Brightness"]
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z", begin["started_utc"])
    assert end["line"] == "end" and end["seq"] == 1 and end["ok"] is True
    assert (end["delivery"], end["retry"], end["error"]) == (wire["delivery"], wire["retry"], None)
    assert end["input"] == "tap" and end["gate"] == wire["data"]["gate"]
    assert end["target"] == {"ref": ref, "query": None, "role": "button", "name": "Display"}


@todo
def test_the_trace_is_one_private_file_per_device_and_utc_day(tmp_path):
    invoke(["snapshot"], hub(), tmp_path)
    invoke(["snapshot"], hub(), tmp_path)
    path = trace_file(tmp_path)
    assert re.fullmatch(r"\d{4}-\d\d-\d\d\.jsonl", path.name)
    assert mode(path) == 0o600 and mode(path.parent) == 0o700 and mode(path.parent.parent) == 0o700
    assert [line["seq"] for line in lines(tmp_path)] == [0, 0, 1, 1]


@todo
def test_a_refused_command_has_an_end_line_with_its_error(tmp_path):
    invoke(["snapshot"], hub(), tmp_path)
    code, _ = invoke(["click", "name=Nowhere", "--timeout-ms", "100"], hub(), tmp_path)
    end = lines(tmp_path)[-1]
    assert code == 1 and (end["ok"], end["error"], end["delivery"]) == (False, "NOT_FOUND", "not_delivered")
    assert end["target"] == {"ref": None, "query": 'name="Nowhere"', "role": None, "name": None}


@todo
def test_the_text_a_command_typed_is_not_in_the_trace(tmp_path):
    phone = hub(SEARCH, SEARCH)
    invoke(["snapshot"], phone, tmp_path)
    invoke(["set-text", "name=Search settings", "hunter2"], phone, tmp_path)
    invoke(["clipboard", "set", "hunter2"], phone, tmp_path)
    assert "hunter2" not in trace_file(tmp_path).read_text()
    typed, copied = (line for line in lines(tmp_path) if line["line"] == "begin" and line["seq"] > 0)
    assert typed["argv"] == ["set-text", "name=Search settings", "<7 chars>"]
    assert (copied["command"], copied["argv"]) == ("clipboard set", ["clipboard", "set", "<7 chars>"])


@todo
@pytest.mark.parametrize(
    "argv",
    [
        ["-d", J7_SERIAL, "press", "back"],
        ["press", "back", "--device", J7_SERIAL],
        [f"--device={J7_SERIAL}", "press", "back"],
    ],
)
def test_the_argv_of_a_line_starts_at_the_command_and_names_no_device(tmp_path, argv):
    invoke(["snapshot"], hub(), tmp_path)
    invoke(argv, hub(), tmp_path)
    assert lines(tmp_path)[2]["argv"] == ["press", "back"]


@todo
def test_a_command_that_dies_leaves_a_begin_line_with_no_end_line(tmp_path):
    class Broken(FakePhone):
        def read(self):
            raise RuntimeError("the backend fell over")

    class BrokenHub(FakeHub):
        def open(self, serial, first_read=False):
            return Broken(self._infos[serial])

    code, wire = invoke(["snapshot"], BrokenHub([J7]), tmp_path)
    assert code == 1 and wire["error"]["code"] == "INTERNAL"
    assert [(line["line"], line["command"]) for line in lines(tmp_path)] == [("begin", "snapshot")]


def test_a_command_that_chose_no_device_leaves_no_trace(tmp_path):
    invoke(["devices"], hub(), tmp_path)
    invoke(["skills", "list"], hub(), tmp_path)
    invoke(["click", "name=Display"], FakeHub([]), tmp_path)
    assert not (tmp_path / "traces").exists()
