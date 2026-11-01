"""`agent-phone batch` as an agent runs it: steps that are the CLI's own argv arrays, run in one
process under one device lock, stopped at the first step that is not ok. Each case reads what
reached the fake device, so "nothing was sent" is an observation, and the trace file that the
batch left, so "what each step did" is read from the file an agent reads."""

import io
import json
import os
import re
import stat
from datetime import datetime

import pytest
from fakes import EMULATOR_SERIAL, J7_SERIAL, FakeHub, FakePhone, info_for, invoke
from support import fixture_screen, node, screen_of

from agent_phone.core.device import Connected
from agent_phone.core.phone import Key, Launch, Tap

J7 = Connected(J7_SERIAL, "SM_J730F", ready=True)
EMULATOR = Connected(EMULATOR_SERIAL, "emu", ready=True)
HOME = screen_of(
    node(
        "android.widget.FrameLayout",
        node("android.widget.TextView", text="Home screen", bounds="[0,200][1080,300]"),
        package="com.sec.android.app.launcher",
        bounds="[0,0][1080,1920]",
    )
)
SETTINGS = fixture_screen("settings-home")
BRIGHTNESS = screen_of(
    node(
        "android.widget.FrameLayout",
        node("android.widget.TextView", text="Brightness", bounds="[0,200][1080,300]"),
        package="com.android.settings",
        bounds="[0,0][1080,1920]",
    )
)
LAUNCH = ["launch", "com.android.settings", "--wait-for", "name=Display"]
OPEN_DISPLAY = ["click", "name=Display", "--wait-for", "name*=Brightness"]
BACK = ["press", "back", "--wait-for", "name=Display"]
THREE = [LAUNCH, OPEN_DISPLAY, BACK]
DISPLAY_COMMITS = (
    '[[commit]]\nid = "t.display"\neffect = "confirm"\nwords = ["display"]\n'
    'packages = ["com.android.settings"]\nreason = "A test commit."\n'
)


def flow(*connected):
    """Home, then Settings after the launch, the Display page after the tap, Settings after back."""
    return FakeHub(connected or [J7], screens=[HOME], after_each=[SETTINGS, BRIGHTNESS, SETTINGS])


def look(root, screen=HOME):
    code, wire = invoke(["snapshot"], FakeHub([J7], screens=[screen]), root)
    assert code == 0
    return wire["data"]["id"]


def batch(root, steps, hub, *flags, name="steps.json"):
    path = root / name
    path.write_text(steps if isinstance(steps, str) else json.dumps(steps))
    return invoke(["batch", *flags, str(path)], hub, root)


def sent(hub):
    return [permit.action for phone in hub.phones for permit in phone.permits]


def traces(root):
    return sorted((root / "traces" / J7_SERIAL).glob("*-batch.jsonl"))


def trace_lines(root):
    [path] = traces(root)
    return [json.loads(line) for line in path.read_text().splitlines()]


def shape(wire):
    """The envelope with its snapshot ids blanked, which differ from one run to the next."""
    text = json.dumps(wire, ensure_ascii=False, sort_keys=True)
    return json.loads(re.sub(r"@[0-9a-z]{5}:", "@_:", re.sub(r'"id": "[0-9a-z]{5}"', '"id": "_"', text)))


def test_three_steps_run_in_one_call_and_each_stands_as_its_command_would_alone(tmp_path):
    look(tmp_path)
    hub = flow()
    code, wire = batch(tmp_path, THREE, hub)
    assert code == 0 and wire["ok"] is True and wire["command"] == "batch" and wire["device"] == J7_SERIAL
    assert (wire["delivery"], wire["retry"]) == ("delivered_verified", "unsafe")
    steps = wire["data"]["steps"]
    assert wire["data"]["stopped_at"] is None
    assert [s["command"] for s in steps] == ["launch", "click", "press"]
    assert [s["delivery"] for s in steps] == ["delivered_verified"] * 3
    assert steps[1]["data"]["target"]["ref"] is None and steps[1]["data"]["target"]["name"] == "Display"
    assert [type(action) for action in sent(hub)] == [Launch, Tap, Key]
    assert len(hub.phones) == 1 and hub.phones[0].closed, "one process opens the phone once"

    alone = tmp_path / "alone"
    look(alone)
    screens, afters = [HOME, SETTINGS, BRIGHTNESS], [SETTINGS, BRIGHTNESS, SETTINGS]
    singles = [
        invoke(argv, FakeHub([J7], screens=[screen], after_input=[after]), alone)[1]
        for argv, screen, after in zip(THREE, screens, afters, strict=True)
    ]
    assert [shape(step) for step in steps] == [shape(single) for single in singles]


def test_a_batch_stops_at_its_first_failed_step_and_takes_that_steps_error_and_delivery(tmp_path):
    look(tmp_path)
    hub = flow()
    nowhere = ["click", "name=Nowhere", "--timeout-ms", "100"]
    code, wire = batch(tmp_path, [LAUNCH, nowhere, BACK], hub)
    steps = wire["data"]["steps"]
    assert code == 1 and wire["ok"] is False and wire["data"]["stopped_at"] == 1 and len(steps) == 2
    assert wire["error"] == steps[1]["error"] and wire["error"]["code"] == "NOT_FOUND"
    assert wire["delivery"] == steps[1]["delivery"] == "not_delivered"
    assert wire["retry"] == "unsafe" and steps[1]["retry"] == "safe", "the launch before it went out"
    assert [type(action) for action in sent(hub)] == [Launch]


def test_a_batch_that_stops_before_any_input_is_safe_to_run_again(tmp_path):
    hub = FakeHub([J7], screens=[HOME])
    code, wire = batch(tmp_path, [["wait", "--for", "name=Nowhere", "--timeout-ms", "100"], BACK], hub)
    assert code == 1 and wire["error"]["code"] == "TIMEOUT" and wire["data"]["stopped_at"] == 0
    assert (wire["delivery"], wire["retry"]) == ("not_delivered", "safe")
    assert len(wire["data"]["steps"]) == 1 and sent(hub) == []
    look(tmp_path)
    code, wire = batch(tmp_path, [["click", "name=Nowhere", "--timeout-ms", "100"], BACK], hub)
    assert (wire["delivery"], wire["retry"]) == ("not_delivered", "safe") and sent(hub) == []


@pytest.mark.xfail(strict=True, reason="the batch's error repeats the failed step's whole error, details too")
def test_a_failed_batch_names_the_failed_step_and_does_not_print_its_details_twice(tmp_path):
    hub = FakeHub([J7], screens=[HOME])
    code, wire = batch(tmp_path, [["wait", "--for", "name=Nowhere", "--timeout-ms", "100"], BACK], hub)
    step = wire["data"]["steps"][0]["error"]
    assert step["details"]["after"] is not None, "the step keeps the snapshot it timed out on"
    assert wire["error"] == {
        "code": step["code"],
        "message": step["message"],
        "hint": step["hint"],
        "details": {"step": 0},
    }, "the batch's error points at the step, and the step holds the details once"


def test_a_step_that_went_out_and_then_failed_keeps_its_own_delivery(tmp_path):
    look(tmp_path)
    hub = flow()
    never = ["launch", "com.android.settings", "--wait-for", "name=Nowhere", "--timeout-ms", "100"]
    code, wire = batch(tmp_path, [never, BACK], hub)
    assert code == 1 and wire["error"]["code"] == "TIMEOUT" and wire["data"]["stopped_at"] == 0
    assert (wire["delivery"], wire["retry"]) == ("delivered_unverified", "unsafe")
    assert wire["data"]["steps"][0]["data"]["after"] is not None


def test_two_refs_from_one_snapshot_still_fail_as_the_second_is_spent(tmp_path):
    taken = look(tmp_path, SETTINGS)
    hub = FakeHub([J7], screens=[SETTINGS], after_each=[BRIGHTNESS])
    steps = [["click", f"@{taken}:e7", "--wait-for", "name=Brightness"], ["click", f"@{taken}:e6"]]
    code, wire = batch(tmp_path, steps, hub)
    assert code == 1 and wire["error"]["code"] == "STALE_REF" and wire["data"]["stopped_at"] == 1
    assert wire["error"]["details"] == {"reason": "spent"} and wire["retry"] == "unsafe"
    assert [type(action) for action in sent(hub)] == [Tap]


def test_a_ref_in_a_step_names_the_device_when_no_d_does(tmp_path):
    taken = look(tmp_path, SETTINGS)
    hub = FakeHub([J7, EMULATOR], screens=[SETTINGS], after_each=[BRIGHTNESS])
    code, wire = batch(tmp_path, [["click", f"@{taken}:e7", "--wait-for", "name=Brightness"]], hub)
    assert code == 0 and wire["device"] == J7_SERIAL
    code, wire = batch(tmp_path, [BACK], flow(J7, EMULATOR), name="two.json")
    assert code == 1 and wire["error"]["code"] == "DEVICE_AMBIGUOUS" and wire["command"] == "batch"
    assert "data" not in wire


def test_d_is_given_once_on_the_batch(tmp_path):
    look(tmp_path)
    hub = flow(J7, EMULATOR)
    code, wire = batch(tmp_path, THREE, hub, "-d", J7_SERIAL)
    assert code == 0 and wire["device"] == J7_SERIAL and len(sent(hub)) == 3


@pytest.mark.parametrize(
    "step",
    [
        ["-d", J7_SERIAL, "press", "back"],
        ["press", "back", "-d", J7_SERIAL],
        ["press", "back", "--device", EMULATOR_SERIAL],
    ],
)
def test_a_step_that_names_its_own_device_fails_the_batch_before_any_step_runs(tmp_path, step):
    look(tmp_path)
    hub = flow()
    code, wire = batch(tmp_path, [LAUNCH, step], hub)
    assert code == 2 and wire["command"] == "batch" and wire["error"]["code"] == "INVALID_ARGS"
    assert "steps[1]" in wire["error"]["message"] and "-d" in wire["error"]["message"]
    assert (wire["delivery"], wire["retry"]) == ("not_delivered", "safe")
    assert hub.phones == [] and traces(tmp_path) == []


@pytest.mark.parametrize(
    "step",
    [
        ["batch", "steps.json"],
        ["server", "start"],
        ["server", "stop"],
        ["server", "status"],
        ["devices"],
        ["skills", "list"],
        ["press", "--help"],
        ["click", "Display"],
        ["click", "@k3x9q:e7", "--wait-for", "Display"],
        ["press", "power"],
    ],
)
def test_a_step_that_is_not_a_command_on_the_phone_or_does_not_parse_runs_nothing(tmp_path, step):
    look(tmp_path)
    hub = flow()
    code, wire = batch(tmp_path, [LAUNCH, step], hub)
    assert code == 2 and wire["command"] == "batch" and wire["error"]["code"] == "INVALID_ARGS"
    assert "steps[1]" in wire["error"]["message"] and wire["retry"] == "safe"
    assert hub.phones == [] and traces(tmp_path) == []


@pytest.mark.parametrize(
    "text",
    ["", "not json", "{}", "[]", '["press", "back"]', "[[]]", "[[1]]", '[["press", "back"], "click"]'],
)
def test_steps_that_are_not_an_array_of_argv_arrays_fail_before_the_phone_is_opened(tmp_path, text):
    hub = flow()
    code, wire = batch(tmp_path, text, hub)
    assert code == 2 and wire["command"] == "batch" and wire["error"]["code"] == "INVALID_ARGS"
    assert hub.phones == [] and traces(tmp_path) == []


def test_a_missing_file_is_refused_and_stdin_is_read_for_a_dash_or_no_file(tmp_path):
    look(tmp_path)
    hub = flow()
    code, wire = invoke(["batch", str(tmp_path / "nowhere.json")], hub, tmp_path)
    assert code == 2 and wire["command"] == "batch" and wire["error"]["code"] == "INVALID_ARGS"
    assert hub.phones == []
    code, wire = invoke(["batch", "-"], flow(), tmp_path, stdin=io.StringIO(json.dumps(THREE)))
    assert code == 0 and len(wire["data"]["steps"]) == 3
    look(tmp_path)
    code, wire = invoke(["batch"], flow(), tmp_path, stdin=io.StringIO(json.dumps([BACK])))
    assert code == 0 and len(wire["data"]["steps"]) == 1

    class Terminal(io.StringIO):
        def isatty(self):
            return True

    look(tmp_path)
    hub = flow()
    code, wire = invoke(["batch"], hub, tmp_path, stdin=Terminal(""))
    assert code == 2 and wire["error"]["code"] == "INVALID_ARGS" and hub.phones == []


def test_commit_is_allowed_inside_a_step_and_never_on_the_batch(tmp_path):
    rule = tmp_path / "display.toml"
    rule.write_text(DISPLAY_COMMITS)
    look(tmp_path)
    hub = flow()
    click = ["click", "name=Display", "--policy", str(rule)]
    code, wire = batch(tmp_path, [LAUNCH, click], hub)
    assert code == 1 and wire["error"]["code"] == "COMMIT_REFUSED" and wire["data"]["stopped_at"] == 1
    assert [type(action) for action in sent(hub)] == [Launch]
    look(tmp_path)
    hub = flow()
    code, wire = batch(tmp_path, [LAUNCH, [*click, "--commit", "confirm"]], hub)
    assert code == 0 and wire["data"]["steps"][1]["data"]["gate"]["effects"] == ["confirm"]
    assert [type(action) for action in sent(hub)] == [Launch, Tap]
    look(tmp_path)
    code, wire = batch(tmp_path, THREE, flow(), "--commit", "confirm", name="grant.json")
    assert code == 2 and wire["error"]["code"] == "INVALID_ARGS"


def test_a_grant_and_a_policy_file_serve_only_the_step_that_names_them(tmp_path):
    rule = tmp_path / "display.toml"
    rule.write_text(DISPLAY_COMMITS)
    look(tmp_path, SETTINGS)
    granted = [
        "click",
        "name=Display",
        "--policy",
        str(rule),
        "--commit",
        "confirm",
        "--wait-for",
        "name=Display",
    ]
    hub = FakeHub([J7], screens=[SETTINGS], after_each=[SETTINGS, SETTINGS])
    code, wire = batch(tmp_path, [granted, ["click", "name=Display", "--policy", str(rule)]], hub)
    assert code == 1 and wire["data"]["stopped_at"] == 1 and wire["error"]["code"] == "COMMIT_REFUSED"
    assert wire["error"]["details"]["granted"] == [] and len(sent(hub)) == 1
    look(tmp_path, SETTINGS)
    hub = FakeHub([J7], screens=[SETTINGS], after_each=[SETTINGS, SETTINGS])
    code, wire = batch(tmp_path, [granted, ["click", "name=Display"]], hub, name="plain.json")
    assert code == 0 and len(sent(hub)) == 2, "the file of the first step is not the second step's"


def test_a_policy_file_that_does_not_parse_runs_no_step(tmp_path):
    bad = tmp_path / "bad.toml"
    bad.write_text("[[commit]]\nid = 7\n")
    look(tmp_path)
    hub = flow()
    code, wire = batch(tmp_path, [LAUNCH, ["click", "name=Display", "--policy", str(bad)]], hub)
    assert code == 1 and wire["error"]["code"] == "POLICY_INVALID" and wire["retry"] == "safe"
    assert sent(hub) == [] and "data" not in wire


def test_the_batch_holds_the_device_lock_from_its_first_step_to_its_last(tmp_path):
    seen = []

    class Watched(FakePhone):
        def read(self):
            if self.reads == 1:
                seen.append(invoke(["press", "back"], FakeHub([J7], screens=[HOME]), tmp_path)[1])
            return super().read()

    class Hub(FakeHub):
        def open(self, serial, first_read=False):
            phone = Watched(info_for(serial), HOME)
            self.phones.append(phone)
            return phone

    wait = ["wait", "--for", "name=Home screen"]
    code, wire = batch(tmp_path, [wait, wait], Hub([J7]))
    assert code == 0 and [s["ok"] for s in wire["data"]["steps"]] == [True, True]
    [other] = seen
    assert other["error"]["code"] == "DEVICE_BUSY" and other["delivery"] == "not_delivered"
    assert invoke(["press", "back"], FakeHub([J7], screens=[HOME]), tmp_path)[0] == 0, "released after"


def test_an_ok_batch_has_a_delivery_only_when_it_sent_and_it_is_the_weakest_of_its_inputs(tmp_path):
    hub = FakeHub([J7], screens=[SETTINGS])
    code, wire = batch(tmp_path, [["wait", "--for", "name=Display"], ["find", "--name", "Display"]], hub)
    assert code == 0 and "delivery" not in wire and "retry" not in wire and "error" not in wire
    look(tmp_path)
    hub = FakeHub([J7], screens=[HOME])
    code, wire = batch(
        tmp_path, [["press", "back"], ["wait", "--for", "name=Home screen"]], hub, name="a.json"
    )
    assert code == 0 and (wire["delivery"], wire["retry"]) == ("delivered_unverified", "unsafe")
    look(tmp_path)
    code, wire = batch(tmp_path, [LAUNCH, ["press", "back"]], flow(), name="b.json")
    assert code == 0 and wire["delivery"] == "delivered_unverified"
    assert [s["delivery"] for s in wire["data"]["steps"]] == ["delivered_verified", "delivered_unverified"]


def test_a_batch_that_cannot_open_the_phone_still_prints_one_batch_envelope(tmp_path):
    code, wire = batch(tmp_path, THREE, FakeHub([]))
    assert code == 1 and wire["command"] == "batch" and wire["error"]["code"] == "NO_DEVICE"
    assert (wire["delivery"], wire["retry"]) == ("not_delivered", "safe") and "data" not in wire


def test_the_trace_lists_each_step_with_what_it_sent_and_ends_with_the_total(tmp_path):
    look(tmp_path)
    code, wire = batch(tmp_path, THREE, flow())
    [path] = traces(tmp_path)
    assert code == 0 and wire["data"]["trace"] == str(path)
    assert path.parent == tmp_path / "traces" / J7_SERIAL and path.name.endswith("-batch.jsonl")
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(path.parent).st_mode) == 0o700
    *steps, end = trace_lines(tmp_path)
    assert [line["i"] for line in steps] == [0, 1, 2] and [line["argv"] for line in steps] == THREE
    assert all(line["line"] == "step" and line["ok"] is True for line in steps)
    assert [(s["delivery"], s["retry"], s["error"]) for s in steps] == [
        ("delivered_verified", "unsafe", None)
    ] * 3
    assert [s["input"] for s in steps] == ["launch", "tap", "key"]
    assert steps[0]["target"] is None and steps[2]["target"] is None
    assert steps[1]["target"] == {"ref": None, "query": 'name="Display"', "role": "button", "name": "Display"}
    assert steps[1]["gate"] == {"verdict": "clear", "reason": "no_commit_words"}
    for line in steps:
        assert isinstance(line["ms"], int) and line["ms"] >= 0
        assert datetime.fromisoformat(line["started_utc"]).utcoffset().total_seconds() == 0
        assert "after" not in line and "tree" not in json.dumps(line)
    assert end["line"] == "end" and end["stopped_at"] is None and end["ms"] >= 0


def test_the_trace_of_a_stopped_batch_ends_at_the_failed_step_and_keeps_what_was_asked(tmp_path):
    look(tmp_path)
    nowhere = ["click", "name=Nowhere", "--timeout-ms", "100"]
    code, wire = batch(tmp_path, [LAUNCH, nowhere, BACK], flow())
    *steps, end = trace_lines(tmp_path)
    assert code == 1 and [line["i"] for line in steps] == [0, 1] and end["stopped_at"] == 1
    failed = steps[1]
    assert (failed["ok"], failed["error"], failed["delivery"], failed["retry"]) == (
        False,
        "NOT_FOUND",
        "not_delivered",
        "safe",
    )
    assert failed["input"] is None and failed["gate"] is None
    assert failed["target"] == {"ref": None, "query": 'name="Nowhere"', "role": None, "name": None}


def test_a_read_step_has_a_line_with_no_delivery_and_no_input(tmp_path):
    hub = FakeHub([J7], screens=[SETTINGS])
    code, _ = batch(tmp_path, [["wait", "--for", "name=Display"], ["snapshot"]], hub)
    steps = trace_lines(tmp_path)[:-1]
    assert code == 0 and [line["argv"][0] for line in steps] == ["wait", "snapshot"]
    assert all(
        line["delivery"] is None and line["input"] is None and line["target"] is None for line in steps
    )


def test_the_trace_never_holds_the_text_a_step_typed(tmp_path):
    def search(text=""):
        return screen_of(
            node(
                "android.widget.FrameLayout",
                node(
                    "android.widget.EditText",
                    text=text,
                    hint="Search",
                    clickable=True,
                    bounds="[0,100][1080,200]",
                ),
                package="com.android.settings",
                bounds="[0,0][1080,1920]",
            )
        )

    look(tmp_path, search())
    hub = FakeHub([J7], screens=[search()], after_input=[search("hunter2")])
    steps = [["set-text", "role=field", "hunter2"], ["clipboard", "set", "hunter2 again"]]
    code, wire = batch(tmp_path, steps, hub)
    [path] = traces(tmp_path)
    assert code == 0 and "hunter2" not in path.read_text()
    assert "hunter2" not in json.dumps(wire["data"]["steps"][1])
    first, second, _ = trace_lines(tmp_path)
    assert first["argv"] == ["set-text", "role=field", "<7 chars>"]
    assert second["argv"] == ["clipboard", "set", "<13 chars>"]


def test_a_step_that_raises_leaves_a_trace_of_the_steps_before_it_and_a_line_for_itself(tmp_path):
    class Breaks(FakePhone):
        def read(self):
            if self.permits:
                raise RuntimeError("the backend fell over between two steps")
            return super().read()

    class Hub(FakeHub):
        def open(self, serial, first_read=False):
            phone = Breaks(info_for(serial), HOME)
            self.phones.append(phone)
            return phone

    look(tmp_path)
    hub = Hub([J7])
    code, wire = batch(tmp_path, [["press", "back"], ["wait", "--for", "name=Home screen"], BACK], hub)
    steps = wire["data"]["steps"]
    assert code == 1 and wire["data"]["stopped_at"] == 1 and len(steps) == 2 and steps[0]["ok"] is True
    assert wire["error"]["code"] == "INTERNAL" and steps[1]["error"]["code"] == "INTERNAL"
    assert (steps[1]["delivery"], wire["delivery"], wire["retry"]) == ("not_delivered",) * 2 + ("unsafe",)
    first, second, end = trace_lines(tmp_path)
    assert first["ok"] is True and first["input"] == "key" and first["argv"] == ["press", "back"]
    assert (second["i"], second["ok"], second["error"]) == (1, False, "INTERNAL")
    assert end["stopped_at"] == 1 and len(sent(hub)) == 1
