"""`agent-phone flow run FILE` as an agent runs it: a job written once as a file of steps, each
the CLI's own argv with a query for its target, replayed in one process with no agent turn. Each
case reads what reached the fake phone, so "nothing was sent" is an observation."""

import json

import pytest
from fakes import J7_SERIAL, FakeHub, invoke
from support import ROOT, fixture_screen, node, screen_of, search_field

from agent_phone.core.device import Connected
from agent_phone.core.phone import Key, Launch, SetText, Tap

J7 = Connected(J7_SERIAL, "SM_J730F", ready=True)
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
SEARCH = (ROOT / "examples" / "flows" / "settings-search.toml").read_text()
DISPLAY_COMMITS = (
    '[[commit]]\nid = "t.display"\neffect = "confirm"\nwords = ["display"]\n'
    'packages = ["com.android.settings"]\nreason = "A test commit."\n'
)


def search_hub():
    return FakeHub([J7], screens=[HOME], after_each=[search_field(), search_field("battery")])


def display_hub():
    """Home, then Settings after the launch, the Display page after the tap, Settings after back."""
    return FakeHub([J7], screens=[HOME], after_each=[SETTINGS, BRIGHTNESS, SETTINGS])


def display_flow(root, grants='["confirm"]', commit=("--commit", "confirm")):
    """Launch Settings, tap Display under a rule that makes the tap a commit, and go back."""
    rule = root / "display.toml"
    rule.write_text(DISPLAY_COMMITS)
    click = ["click", "name=Display", "--policy", str(rule), "--wait-for", "name=Brightness", *commit]
    return (
        f'[flow]\nname = "display"\ngrants = {grants}\n\n'
        '[[step]]\nrun = ["launch", "com.android.settings", "--wait-for", "name=Display"]\n\n'
        f"[[step]]\nrun = {json.dumps(click)}\n\n"
        '[[step]]\nrun = ["press", "back", "--wait-for", "name=Display"]\n'
    )


def run(root, text, hub, *flags, env=None):
    path = root / "flow.toml"
    path.write_text(text)
    return invoke(["flow", "run", str(path), *flags], hub, root, env=env)


def sent(hub):
    return [permit.action for phone in hub.phones for permit in phone.permits]


def trace_lines(root):
    [path] = (root / "traces" / J7_SERIAL).iterdir()
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_the_settings_flow_runs_from_a_cold_start_and_prints_one_small_envelope(tmp_path):
    hub = search_hub()
    code, wire = run(tmp_path, SEARCH, hub, "--param", "query=battery")
    assert code == 0 and wire["ok"] is True and wire["command"] == "flow run" and wire["device"] == J7_SERIAL
    assert (wire["delivery"], wire["retry"]) == ("delivered_unverified", "unsafe"), (
        "the launch proved nothing"
    )
    data = wire["data"]
    assert (data["flow"], data["steps"], data["ran"], data["stopped_at"]) == ("settings-search", 2, 2, None)
    size = len(json.dumps(wire, separators=(",", ":"))) - len(data["trace"])
    assert "error" not in wire and size < 300, "a replay costs one small object, whatever its steps printed"
    launch, typed = sent(hub)
    assert isinstance(launch, Launch) and isinstance(typed, SetText) and typed.text == "battery"
    assert len(hub.phones) == 1 and hub.phones[0].closed, "one process opens the phone once"


def test_a_flow_runs_only_when_the_caller_grants_every_declared_effect(tmp_path):
    hub = display_hub()
    code, wire = run(tmp_path, display_flow(tmp_path), hub)
    assert code == 1 and wire["command"] == "flow run" and wire["error"]["code"] == "COMMIT_REFUSED"
    assert (wire["delivery"], wire["retry"]) == ("not_delivered", "safe")
    assert hub.phones == [], "the phone is not opened for a flow the caller did not grant"
    code, wire = run(tmp_path, display_flow(tmp_path), hub, "--commit", "confirm")
    assert code == 0 and wire["data"]["ran"] == 3 and wire["delivery"] == "delivered_verified"
    assert [type(action) for action in sent(hub)] == [Launch, Tap, Key]


def test_dangerously_skip_lifts_the_callers_grant_as_it_lifts_a_steps(tmp_path):
    hub = display_hub()
    env = {"AGENT_PHONE_PERMISSION_MODE": "dangerously-skip"}
    code, wire = run(tmp_path, display_flow(tmp_path, commit=()), hub, env=env)
    assert code == 0 and wire["permission_mode"] == "dangerously-skip" and wire["data"]["ran"] == 3
    assert [type(action) for action in sent(hub)] == [Launch, Tap, Key]


def test_a_step_whose_commit_is_outside_the_grants_fails_at_load(tmp_path):
    hub = display_hub()
    code, wire = run(tmp_path, display_flow(tmp_path, grants="[]"), hub, "--commit", "confirm")
    assert code == 2 and wire["command"] == "flow run" and wire["error"]["code"] == "INVALID_ARGS"
    assert hub.phones == [], "no step runs, not even the launch before it"


def test_a_permit_whose_effect_the_flow_did_not_declare_is_refused(tmp_path):
    hub = display_hub()
    undeclared = display_flow(tmp_path, grants="[]", commit=())
    code, wire = run(tmp_path, undeclared, hub, "--commit", "confirm")
    assert code == 1 and wire["error"]["code"] == "COMMIT_REFUSED" and wire["error"]["details"]["step"] == 1
    assert wire["data"]["stopped_at"] == 1 and wire["data"]["ran"] == 1
    assert [type(action) for action in sent(hub)] == [Launch], "the caller's grant reaches no step"


@pytest.mark.parametrize("mode", ["ask", "dangerously-skip"])
def test_dry_run_stops_before_the_first_commit(tmp_path, mode):
    hub = display_hub()
    env = {"AGENT_PHONE_PERMISSION_MODE": mode}
    code, wire = run(tmp_path, display_flow(tmp_path), hub, "--dry-run", env=env)
    assert code == 0 and wire["ok"] is True and "error" not in wire
    data = wire["data"]
    assert (data["dry_run"], data["stopped_at"], data["ran"], data["commit"]) == (True, 1, 1, ["confirm"])
    assert wire["permission_mode"] == "ask", "a dry run judges every step as ask does"
    assert [type(action) for action in sent(hub)] == [Launch], "the commit and the steps after it stay unsent"


def test_a_dry_run_fails_on_a_commit_that_the_real_run_would_refuse(tmp_path):
    hub = display_hub()
    undeclared = display_flow(tmp_path, commit=())
    code, wire = run(tmp_path, undeclared, hub, "--dry-run")
    assert code == 1 and wire["ok"] is False and wire["error"]["code"] == "COMMIT_REFUSED"
    assert (wire["error"]["details"]["step"], wire["data"]["commit"]) == (1, None)
    assert [type(action) for action in sent(hub)] == [Launch]


def test_a_dry_run_of_a_flow_with_no_commit_runs_every_step(tmp_path):
    hub = search_hub()
    code, wire = run(tmp_path, SEARCH, hub, "--param", "query=battery", "--dry-run")
    data = wire["data"]
    assert code == 0 and (data["dry_run"], data["stopped_at"], data["ran"], data["commit"]) == (
        True,
        None,
        2,
        None,
    )
    assert len(sent(hub)) == 2


@pytest.mark.parametrize(
    "step",
    [
        ["click", "@k3x9q:e7"],
        ["set-text", "@k3x9q:e7", "battery"],
        ["scroll", "down", "@k3x9q:e3"],
        ["get", "@k3x9q:e7"],
        ["snapshot", "--root", "@k3x9q:e3"],
        ["click", "@k3x9q:540,1450"],
    ],
    ids=["click", "set-text", "scroll", "get", "root", "point"],
)
def test_a_step_with_a_ref_or_a_point_is_refused_at_load(tmp_path, step):
    hub = display_hub()
    launch = '[[step]]\nrun = ["launch", "com.android.settings"]\n\n'
    text = f'[flow]\nname = "by-ref"\n\n{launch}[[step]]\nrun = {json.dumps(step)}\n'
    code, wire = run(tmp_path, text, hub)
    assert code == 2 and wire["command"] == "flow run" and wire["error"]["code"] == "INVALID_ARGS"
    assert hub.phones == []


def test_a_flow_stops_at_the_first_unmet_expectation_and_says_which_step(tmp_path):
    hub = FakeHub([J7], screens=[HOME], after_each=[SETTINGS])
    code, wire = run(tmp_path, SEARCH, hub, "--param", "query=battery")
    error = wire["error"]
    assert code == 1 and wire["ok"] is False and error["code"] == "TIMEOUT"
    assert (error["details"]["step"], error["details"]["during"]) == (1, "expect")
    assert "Search settings" in error["message"]
    assert error["details"]["after"]["app"] == "com.android.settings", "the screen it stopped on, with refs"
    assert (wire["data"]["stopped_at"], wire["data"]["ran"]) == (1, 1)
    assert (wire["delivery"], wire["retry"]) == ("not_delivered", "unsafe"), "the launch before it went out"
    assert [type(action) for action in sent(hub)] == [Launch]


def test_a_flow_stops_at_the_first_failed_step_and_runs_none_after_it(tmp_path):
    hub = display_hub()
    text = (
        '[flow]\nname = "lost"\n\n[[step]]\nrun = ["click", "name=Nowhere", "--timeout-ms", "100"]\n\n'
        '[[step]]\nrun = ["press", "back"]\n'
    )
    code, wire = run(tmp_path, text, hub)
    assert code == 1 and wire["error"]["code"] == "NOT_FOUND"
    assert (wire["error"]["details"]["step"], wire["error"]["details"]["during"]) == (0, "run")
    assert (wire["delivery"], wire["retry"]) == ("not_delivered", "safe") and sent(hub) == []


@pytest.mark.parametrize(
    "flags",
    [
        [],
        ["--param", "query=battery", "--param", "other=1"],
        ["--param", "query"],
        ["--param", "query=a", "--param", "query=b"],
    ],
    ids=["missing", "unknown", "no-value", "twice"],
)
def test_every_parameter_must_be_given_once_and_no_other(tmp_path, flags):
    assert run(tmp_path, SEARCH, search_hub(), "--param", "query=battery")[0] == 0
    hub = search_hub()
    code, wire = run(tmp_path, SEARCH, hub, *flags)
    assert code == 2 and wire["error"]["code"] == "INVALID_ARGS" and hub.phones == []


def test_a_parameter_fills_a_query_too(tmp_path):
    hub = display_hub()
    text = (
        '[flow]\nname = "open"\nparams = ["page", "shows"]\n\n'
        '[[step]]\nrun = ["launch", "com.android.settings", "--wait-for", "name={page}"]\n\n'
        '[[step]]\nexpect = ["name={page}"]\nrun = ["click", "name={page}", "--wait-for", "name={shows}"]\n'
    )
    code, wire = run(tmp_path, text, hub, "--param", "page=Display", "--param", "shows=Brightness")
    assert code == 0 and wire["delivery"] == "delivered_verified"
    assert [type(action) for action in sent(hub)] == [Launch, Tap]


def test_a_value_that_holds_another_parameters_name_is_typed_as_given(tmp_path):
    hub = FakeHub([J7], screens=[HOME], after_each=[search_field(), search_field("{query}")])
    text = SEARCH.replace('params = ["query"]', 'params = ["query", "other"]').replace(
        '"{query}"]', '"{other}"]'
    )
    code, _ = run(tmp_path, text, hub, "--param", "other={query}", "--param", "query=battery")
    assert code == 0 and sent(hub)[1].text == "{query}"


@pytest.mark.parametrize("value", ["--commit=confirm", "--commit", "-x", "--long"])
def test_a_parameter_never_adds_a_flag_to_its_step(tmp_path, value):
    hub = display_hub()
    text = display_flow(tmp_path, commit=("{extra}",)).replace(
        'grants = ["confirm"]', 'grants = ["confirm"]\nparams = ["extra"]'
    )
    code, wire = run(tmp_path, text, hub, "--param", f"extra={value}", "--commit", "confirm")
    assert code == 2 and wire["error"]["code"] == "INVALID_ARGS" and hub.phones == []
    assert value not in json.dumps(wire)


def test_a_value_that_starts_with_a_dash_is_typed_after_a_double_dash(tmp_path):
    hub = FakeHub([J7], screens=[HOME], after_each=[search_field(), search_field("-12 C")])
    refused = run(tmp_path, SEARCH, hub, "--param", "query=-12 C")
    assert refused[0] == 2 and hub.phones == []
    after = SEARCH.replace('"{query}"]', '"--", "{query}"]')
    code, _ = run(tmp_path, after, hub, "--param", "query=-12 C")
    assert code == 0 and sent(hub)[1].text == "-12 C"


def test_a_name_in_braces_that_the_flow_does_not_declare_is_refused(tmp_path):
    hub = search_hub()
    code, wire = run(tmp_path, SEARCH.replace('"{query}"]', '"{qury}"]'), hub, "--param", "query=battery")
    assert code == 2 and wire["error"]["code"] == "INVALID_ARGS" and hub.phones == []


def test_typed_text_reaches_no_trace_line_and_no_envelope_of_a_run_that_is_ok(tmp_path):
    hub = FakeHub([J7], screens=[HOME], after_each=[search_field(), search_field("hunter2")])
    path = tmp_path / "flow.toml"
    path.write_text(SEARCH)
    code, wire = invoke(["flow", "run", str(path), "--param", "query=hunter2"], hub, tmp_path)
    assert code == 0 and sent(hub)[1].text == "hunter2"
    assert "hunter2" not in json.dumps(wire) and path.read_text() == SEARCH
    written = "".join(p.read_text() for p in (tmp_path / "traces").rglob("*") if p.is_file())
    assert "hunter2" not in written and '"{query}"' in written


def test_a_step_gets_a_look_only_when_the_step_before_it_left_no_observation(tmp_path):
    hub = display_hub()
    code, _ = run(tmp_path, display_flow(tmp_path), hub, "--commit", "confirm")
    begun = [line for line in trace_lines(tmp_path) if line["line"] == "begin"]
    assert code == 0 and [(line["command"], line["step"]) for line in begun] == [
        ("snapshot", 0),
        ("launch", 0),
        ("click", 1),
        ("press", 2),
    ], "each --wait-for left the observation the next step needs"


def test_each_step_leaves_its_lines_in_the_trace_of_the_day(tmp_path):
    code, wire = run(tmp_path, SEARCH, search_hub(), "--param", "query=battery")
    lines = trace_lines(tmp_path)
    assert wire["data"]["trace"].endswith(".jsonl") and not wire["data"]["trace"].endswith("-batch.jsonl")
    begun = [line for line in lines if line["line"] == "begin"]
    assert [(line["command"], line["step"]) for line in begun] == [
        ("snapshot", 0),
        ("launch", 0),
        ("wait", 1),
        ("set-text", 1),
    ]
    assert all(line["flow"] == "settings-search" for line in begun)
    assert begun[3]["argv"] == ["set-text", "name=Search settings", "{query}"]
    assert [line["ok"] for line in lines if line["line"] == "end"] == [True] * 4


@pytest.mark.parametrize(
    "text",
    [
        "not toml [",
        '[flow]\nname = "empty"\n',
        '[flow]\n\n[[step]]\nrun = ["press", "back"]\n',
        '[flow]\nname = "x"\nretries = 3\n\n[[step]]\nrun = ["press", "back"]\n',
        '[flow]\nname = "x"\ngrants = ["everything"]\n\n[[step]]\nrun = ["press", "back"]\n',
        '[flow]\nname = "x"\n\n[[step]]\nrun = []\n',
        '[flow]\nname = "x"\n\n[[step]]\nrun = ["press", "back"]\noptional = true\n',
        '[flow]\nname = "x"\n\n[[step]]\nrun = ["devices"]\n',
        '[flow]\nname = "x"\n\n[[step]]\nrun = ["press", "back", "-d", "0a1b2c3d4e5f6a7b"]\n',
        '[flow]\nname = "x"\n\n[[step]]\nexpect = ["Display"]\nrun = ["press", "back"]\n',
    ],
    ids=[
        "toml",
        "no-steps",
        "no-name",
        "flow-key",
        "effect",
        "empty-run",
        "step-key",
        "devices",
        "device",
        "expect",
    ],
)
def test_a_file_that_is_not_a_flow_is_refused_before_the_phone_is_opened(tmp_path, text):
    hub = display_hub()
    code, wire = run(tmp_path, text, hub)
    assert code == 2 and wire["command"] == "flow run" and wire["error"]["code"] == "INVALID_ARGS"
    assert hub.phones == []


def test_a_missing_file_is_refused(tmp_path):
    code, wire = invoke(["flow", "run", str(tmp_path / "none.toml")], display_hub(), tmp_path)
    assert code == 2 and wire["command"] == "flow run" and wire["error"]["code"] == "INVALID_ARGS"
