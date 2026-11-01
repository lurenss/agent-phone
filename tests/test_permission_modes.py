"""The permission modes: `ask`, where a commit needs its grant, and `dangerously-skip`, where it goes
out with none. The mode comes from one environment variable and nothing else. It lifts a commit and
nothing more: every denial, every protected package, the locale guard and every other refusal hold
in both. Each case runs the CLI on a fake phone, so "went out" and "never left" are what the fake's
`permits` list says.

A refusal is only evidence of a mode when the same run shows the mode lets a commit through, so each
test that says "still refused in skip mode" first sends a plain commit under the same environment."""

import json
import sys

import pytest
from fakes import J7_SERIAL, FakeHub, info_for, invoke
from support import FakeClock, node, screen_of
from test_policy_load import GO_LIVE, install_j7

from agent_phone.cli import process
from agent_phone.cli.driver import PhoneError, open_phone
from agent_phone.cli.policy import load_policy
from agent_phone.cli.process import SKILLS_ROOT
from agent_phone.cli.settings import Settings
from agent_phone.core.device import Connected
from agent_phone.core.outcome import ErrorCode, Refusal
from agent_phone.core.phone import Stop, Tap
from agent_phone.core.policy.rules import Effect
from agent_phone.core.query import Q

J7 = Connected(J7_SERIAL, "SM_J730F", ready=True)
VARIABLE = "AGENT_PHONE_PERMISSION_MODE"
SKIP = {VARIABLE: "dangerously-skip"}
ASK_ENVIRONMENTS = [{}, {VARIABLE: ""}, {VARIABLE: "ask"}]
SEND_GATE = {"verdict": "commits", "effects": ["send"]}


def buttons(*labels: str, package: str = "test.app"):
    """A full-screen app with one button for each label, stacked down the screen."""
    return screen_of(
        node(
            "android.widget.FrameLayout",
            *(
                node(
                    "android.widget.Button",
                    text=label,
                    clickable=True,
                    bounds=f"[0,{i * 200}][1080,{i * 200 + 150}]",
                )
                for i, label in enumerate(labels)
            ),
            package=package,
            bounds="[0,0][1080,1920]",
        )
    )


SEND = buttons("Send")


def sent(hub):
    return [permit.action for phone in hub.phones for permit in phone.permits]


def hub_for(screen, locale="en-US"):
    return FakeHub([J7], infos={J7_SERIAL: info_for(J7_SERIAL, locale=locale)}, screens=[screen])


def ref_of(wire, label):
    return next(
        word
        for line in wire["data"]["tree"]
        if f'"{label}"' in line
        for word in line.split()
        if word.startswith("@")
    )


def tap(root, screen, label, *flags, env=None, locale="en-US"):
    """Take a snapshot of `screen`, then click `label` by its ref. The exit code, the envelope, and
    what reached the fake backend."""
    code, wire = invoke(["snapshot"], hub_for(screen, locale), root, env=env)
    assert code == 0, wire
    hub = hub_for(screen, locale)
    code, wire = invoke(["click", ref_of(wire, label), *flags], hub, root, env=env)
    return code, wire, sent(hub)


def skip_sends_a_plain_commit(root):
    """The control for every test below: under `dangerously-skip`, a send goes out with no grant."""
    code, wire, out = tap(root / "control", SEND, "Send", env=SKIP)
    assert code == 0 and len(out) == 1 and wire["mode"] == "dangerously-skip", wire


@pytest.mark.parametrize("env", ASK_ENVIRONMENTS, ids=["unset", "empty", "ask"])
def test_ask_is_the_mode_when_the_variable_is_unset_empty_or_ask(tmp_path, env):
    code, wire, out = tap(tmp_path, SEND, "Send", env=env)
    assert code == 1 and wire["error"]["code"] == "COMMIT_REFUSED" and out == []
    assert wire["mode"] == "ask" and wire["error"]["details"]["granted"] == []


def test_dangerously_skip_sends_a_commit_with_no_grant_and_reports_what_it_skipped(tmp_path):
    code, wire, out = tap(tmp_path, SEND, "Send", env=SKIP)
    assert code == 0 and out != [] and [type(action) for action in out] == [Tap]
    assert wire["mode"] == "dangerously-skip"
    assert wire["data"]["gate"] == SEND_GATE | {"granted": [], "skipped": ["send"]}


def test_the_same_send_in_ask_mode_is_refused_and_sends_nothing(tmp_path):
    code, wire, out = tap(tmp_path, SEND, "Send")
    assert code == 1 and out == [] and wire["mode"] == "ask"
    assert wire["error"]["code"] == "COMMIT_REFUSED" and wire["error"]["details"]["effects"] == ["send"]
    assert wire["delivery"] == "not_delivered" and wire["retry"] == "safe" and "data" not in wire


@pytest.mark.parametrize("env", [{}, SKIP], ids=["ask", "skip"])
def test_an_explicit_commit_goes_out_in_either_mode_and_lists_its_grant(tmp_path, env):
    code, wire, out = tap(tmp_path, SEND, "Send", "--commit", "send", env=env)
    assert code == 0 and len(out) == 1
    assert wire["data"]["gate"] == SEND_GATE | {"granted": ["send"], "skipped": []}


def test_skip_lifts_only_the_effects_the_grant_leaves_and_a_grant_for_another_effect_changes_nothing(
    tmp_path,
):
    both = buttons("Delete and block")
    code, wire, out = tap(tmp_path / "partial", both, "Delete and block", "--commit", "delete", env=SKIP)
    assert code == 0 and len(out) == 1
    assert wire["data"]["gate"] == {
        "verdict": "commits",
        "effects": ["delete", "social"],
        "granted": ["delete"],
        "skipped": ["social"],
    }
    code, wire, out = tap(tmp_path / "other", SEND, "Send", "--commit", "publish", env=SKIP)
    assert code == 0 and len(out) == 1
    assert wire["data"]["gate"] == SEND_GATE | {"granted": [], "skipped": ["send"]}
    code, wire, out = tap(tmp_path / "ask", both, "Delete and block", "--commit", "delete")
    assert code == 1 and out == [] and wire["error"]["details"]["effects"] == ["delete", "social"]


def test_a_clear_tap_has_a_clear_gate_and_the_mode_in_both_modes(tmp_path):
    for env, mode in (({}, "ask"), (SKIP, "dangerously-skip")):
        code, wire, out = tap(tmp_path / mode, buttons("Search"), "Search", env=env)
        assert code == 0 and len(out) == 1 and wire["mode"] == mode
        assert wire["data"]["gate"] == {"verdict": "clear", "reason": "no_commit_words"}


@pytest.mark.parametrize("value", ["skip", "Ask", "ASK", "dangerously_skip", " ask", "ask ", "yes", "1"])
def test_a_value_that_is_neither_mode_is_refused_and_never_read_as_ask(value):
    with pytest.raises(Refusal) as refused:
        Settings.from_environment({VARIABLE: value})
    assert refused.value.code is ErrorCode.INVALID_ARGS
    assert "ask" in refused.value.message and "dangerously-skip" in refused.value.message
    assert repr(value) in refused.value.message


@pytest.mark.parametrize("value", ["skip", "ASK"])
def test_an_invalid_value_stops_the_process_before_any_device_is_opened(monkeypatch, capsys, value):
    """`main()` reads the real environment. Nothing here can reach a device: adb is `false`, and the
    hub the process would build is replaced by one that fails the test."""

    def no_hub(*args, **kwargs):
        raise AssertionError("the process built a hub for a mode it could not read")

    monkeypatch.setenv(VARIABLE, value)
    monkeypatch.setenv("ADB", "false")
    monkeypatch.setattr(sys, "argv", ["agent-phone", "snapshot"])
    monkeypatch.setattr(process, "U2Hub", no_hub)
    assert process.main() == 2
    wire = json.loads(capsys.readouterr().out)
    assert wire["ok"] is False and wire["error"]["code"] == "INVALID_ARGS"
    assert wire["mode"] is None and list(wire)[:4] == ["v", "ok", "command", "mode"]
    assert "ask" in wire["error"]["message"] and "dangerously-skip" in wire["error"]["message"]


@pytest.mark.parametrize(
    "argv",
    [["snapshot"], ["devices"], ["skills", "list"], ["press", "back"], ["click", "name=Nowhere"]],
    ids=lambda argv: argv[0],
)
def test_every_envelope_names_its_mode_right_after_the_command(tmp_path, argv):
    for env, mode in (({}, "ask"), (SKIP, "dangerously-skip")):
        _, wire = invoke(argv, hub_for(SEND), tmp_path / mode, env=env)
        assert list(wire)[:4] == ["v", "ok", "command", "mode"], wire
        assert wire["mode"] == mode


def test_a_failure_the_process_did_not_expect_still_names_its_mode(tmp_path):
    class Breaks(FakeHub):
        def connected(self):
            raise RuntimeError("the hub fell over")

    _, wire = invoke(["snapshot"], Breaks([J7]), tmp_path, env=SKIP)
    assert wire["error"]["code"] == "INTERNAL" and wire["mode"] == "dangerously-skip"


def test_a_batch_runs_its_steps_under_its_own_mode_and_every_record_of_it_names_it(tmp_path):
    steps = tmp_path / "steps.json"
    steps.write_text(json.dumps([["click", "name=Send"]]))
    for env, mode, ok in (({}, "ask", False), (SKIP, "dangerously-skip", True)):
        root = tmp_path / mode
        invoke(["snapshot"], hub_for(SEND), root, env=env)
        hub = hub_for(SEND)
        code, wire = invoke(["batch", str(steps)], hub, root, env=env)
        assert wire["ok"] is ok and wire["mode"] == mode and list(wire)[:4] == ["v", "ok", "command", "mode"]
        assert [step["mode"] for step in wire["data"]["steps"]] == [mode]
        assert len(sent(hub)) == int(ok)
        trace = [json.loads(line) for line in open(wire["data"]["trace"]).read().splitlines()]
        assert [line["mode"] for line in trace if line["line"] == "step"] == [mode]


def test_the_python_api_reads_the_mode_from_the_settings_it_is_given(tmp_path):
    def run(env):
        settings = Settings.from_environment({"AGENT_PHONE_HOME": str(tmp_path), **env})
        hub = hub_for(SEND)
        with open_phone(hub=hub, settings=settings, clock=FakeClock()) as phone:
            phone.snapshot()
            return phone.click(Q("Send")), sent(hub)

    done, out = run(SKIP)
    assert len(out) == 1 and done.report.verdict.effects == {Effect.SEND}
    with pytest.raises(PhoneError) as refused:
        run({})
    assert refused.value.outcome.code is ErrorCode.COMMIT_REFUSED


def test_a_policy_file_cannot_set_the_mode(tmp_path):
    for key in ("mode", "permission_mode"):
        file = tmp_path / f"{key}.toml"
        file.write_text(f'{key} = "dangerously-skip"\n')
        with pytest.raises(Refusal) as refused:
            load_policy([file])
        assert refused.value.code is ErrorCode.POLICY_INVALID and refused.value.details["field"] == key
        code, wire, out = tap(tmp_path / key, SEND, "Send", "--policy", str(file))
        assert code == 1 and wire["error"]["code"] == "POLICY_INVALID" and out == []
        assert wire["mode"] == "ask"


@pytest.mark.parametrize("where", ["top", "device"])
def test_a_device_profile_cannot_set_the_mode(tmp_path, where):
    extra = 'permission_mode = "dangerously-skip"\n'
    device = f'[device]\nserial = "{J7_SERIAL}"\nname = "phone"\n' + (extra if where == "device" else "")
    (tmp_path / "profiles").mkdir()
    (tmp_path / "profiles" / "phone.toml").write_text(device + (extra if where == "top" else ""))
    hub = hub_for(SEND)
    code, wire = invoke(["snapshot"], hub, tmp_path)
    assert code == 1 and wire["error"]["code"] == "POLICY_INVALID" and wire["mode"] == "ask"
    assert hub.phones == []


@pytest.mark.parametrize("flag", ["--mode", "--permission-mode"])
def test_no_command_flag_and_no_batch_step_can_set_the_mode(tmp_path, flag):
    code, wire = invoke(["click", "name=Send", flag, "dangerously-skip"], hub_for(SEND), tmp_path)
    assert code == 2 and wire["error"]["code"] == "INVALID_ARGS" and wire["mode"] == "ask"
    steps = tmp_path / "steps.json"
    steps.write_text(json.dumps([["click", "name=Send", flag, "dangerously-skip"]]))
    code, wire = invoke(["batch", str(steps)], hub_for(SEND), tmp_path)
    assert code == 2 and wire["error"]["code"] == "INVALID_ARGS" and wire["mode"] == "ask"


def test_a_deny_rule_still_refuses_in_skip_mode_with_or_without_a_grant(tmp_path):
    skip_sends_a_plain_commit(tmp_path)
    install_j7(tmp_path)
    for flags in ([], ["--commit", "publish"]):
        code, wire, out = tap(tmp_path, GO_LIVE, "Go live", *flags, env=SKIP)
        assert wire["error"]["code"] == "DENIED" and wire["error"]["details"]["rule"] == "ig.no-live"
        assert out == [] and wire["mode"] == "dangerously-skip"


def test_a_protected_package_is_still_never_stopped_in_skip_mode(tmp_path):
    skip_sends_a_plain_commit(tmp_path)
    (tmp_path / "profiles").mkdir()
    (tmp_path / "profiles" / "phone.toml").write_text(
        f'[device]\nserial = "{J7_SERIAL}"\nname = "phone"\n\n'
        '[[protected]]\npackage = "hev.sockstun"\nlabels = ["SocksTun"]\nreason = "A test protection."\n'
    )
    invoke(["snapshot"], hub_for(SEND), tmp_path, env=SKIP)
    hub = hub_for(SEND)
    code, wire = invoke(["stop", "hev.sockstun"], hub, tmp_path, env=SKIP)
    assert code == 1 and wire["error"]["code"] == "DENIED" and sent(hub) == []
    assert wire["error"]["details"]["rule"] == "profile.protect.hev.sockstun.stop"
    assert wire["mode"] == "dangerously-skip"
    code, _ = invoke(["stop", "com.android.settings"], hub, tmp_path, env=SKIP)
    assert code == 0 and sent(hub) == [Stop("com.android.settings")]


def test_a_language_the_policy_cannot_read_is_still_refused_in_skip_mode(tmp_path):
    skip_sends_a_plain_commit(tmp_path)
    code, wire, out = tap(tmp_path, SEND, "Send", env=SKIP, locale="de-DE")
    assert code == 1 and wire["error"]["code"] == "LOCALE_UNSUPPORTED" and out == []
    assert wire["mode"] == "dangerously-skip"


def test_every_other_refusal_holds_in_skip_mode(tmp_path):
    skip_sends_a_plain_commit(tmp_path)
    two = buttons("Send", "Send")

    def refused(root, code, argv, hub, ahead=None):
        if ahead is not None:
            assert invoke(["snapshot"], ahead, root, env=SKIP)[0] == 0
        _, wire = invoke(argv, hub, root, env=SKIP)
        assert wire["error"]["code"] == code and sent(hub) == [], (code, wire)
        assert wire["mode"] == "dangerously-skip"

    refused(tmp_path / "a", "OBSERVE_FIRST", ["click", "name=Send"], hub_for(SEND))
    refused(tmp_path / "b", "AMBIGUOUS_TARGET", ["click", "name=Send"], hub_for(two), hub_for(two))
    root = tmp_path / "c"
    code, wire = invoke(["snapshot"], hub_for(SEND), root, env=SKIP)
    ref = ref_of(wire, "Send")
    assert invoke(["click", ref], hub_for(SEND), root, env=SKIP)[0] == 0
    hub = hub_for(SEND)
    _, wire = invoke(["click", ref], hub, root, env=SKIP)
    assert wire["error"]["code"] == "STALE_REF" and sent(hub) == []
    covered = screen_of(
        node(
            "android.widget.FrameLayout",
            node(
                "android.widget.Button",
                text="Send",
                clickable=True,
                drawing_order=1,
                bounds="[0,500][1080,600]",
            ),
            node(
                "androidx.recyclerview.widget.RecyclerView",
                node("android.widget.TextView", text="Sheet", bounds="[0,400][1080,450]"),
                scrollable=True,
                drawing_order=2,
                bounds="[0,400][1080,1920]",
            ),
            package="test.app",
            bounds="[0,0][1080,1920]",
        )
    )
    code, wire = invoke(["snapshot"], hub_for(covered), tmp_path / "d", env=SKIP)
    hub = hub_for(covered)
    _, wire = invoke(["click", ref_of(wire, "Send")], hub, tmp_path / "d", env=SKIP)
    assert wire["error"]["code"] == "OCCLUDED" and sent(hub) == []


def test_the_guide_tells_the_agent_never_to_set_the_mode_and_names_both_modes():
    guide = (SKILLS_ROOT / "agent-phone" / "SKILL.md").read_text(encoding="utf-8")
    assert VARIABLE in guide and "`ask`" in guide and "`dangerously-skip`" in guide
    never = [line for line in guide.splitlines() if VARIABLE in line and "never" in line.casefold()]
    assert never, "no line of the guide tells the agent never to set the variable itself"
