"""What a caller's policy file can and cannot change. A consumer's file may weaken a commit, by
exempting a label or disabling a commit rule. It may never weaken a denial, and it may not widen
the languages the engine claims to read. Each case loads real files through the same functions
the CLI uses, and the CLI cases check what reached the backend."""

import shutil

import pytest
from fakes import J7_SERIAL, FakeHub, invoke
from support import ROOT, node, screen_of

from agent_phone.cli.policy import load_policy, load_profile, load_profiles, profile_for
from agent_phone.core.device import Connected
from agent_phone.core.outcome import ErrorCode, Refusal

J7 = Connected(J7_SERIAL, "SM_J730F", ready=True)
INSTAGRAM = "com.instagram.android"
GO_LIVE = screen_of(
    node(
        "android.widget.FrameLayout",
        node(
            "android.widget.Button",
            text="Go live",
            clickable=True,
            bounds="[300,1700][780,1800]",
            package=INSTAGRAM,
        ),
        package=INSTAGRAM,
        bounds="[0,0][1080,1920]",
    )
)


def install_j7(root):
    (root / "profiles").mkdir()
    (root / "instagram").mkdir()
    shutil.copy(ROOT / "examples" / "devices" / "j7.toml", root / "profiles" / "j7.toml")
    shutil.copy(ROOT / "examples" / "instagram" / "policy.toml", root / "instagram" / "policy.toml")


def caller_file(root, text):
    path = root / "caller.toml"
    path.write_text(text)
    return path


def click_go_live(root, *flags):
    code, wire = invoke(["snapshot"], FakeHub([J7], screens=[GO_LIVE]), root)
    assert code == 0, wire
    ref = next(
        t for line in wire["data"]["tree"] if "Go live" in line for t in line.split() if t.startswith("@")
    )
    hub = FakeHub([J7], screens=[GO_LIVE])
    _, wire = invoke(["click", ref, *flags], hub, root)
    return wire, [permit.action for phone in hub.phones for permit in phone.permits]


def test_the_j7_profile_denies_go_live_with_or_without_a_grant(tmp_path):
    install_j7(tmp_path)
    for flags in ([], ["--commit", "publish"]):
        wire, sent = click_go_live(tmp_path, *flags)
        assert wire["error"]["code"] == "DENIED" and wire["error"]["details"]["rule"] == "ig.no-live"
        assert sent == []


def test_a_caller_file_cannot_disable_a_deny_rule_that_the_profile_loads(tmp_path):
    install_j7(tmp_path)
    weaken = caller_file(tmp_path, 'disable = ["ig.no-live"]\n')
    wire, sent = click_go_live(tmp_path, "--policy", str(weaken), "--commit", "publish")
    assert sent == [], f"'Go live' was tapped on the J7 profile: {sent}"
    assert wire["error"]["code"] == "POLICY_INVALID" and wire["error"]["details"]["rule"] == "ig.no-live"


def test_a_second_file_of_the_profile_cannot_disable_the_first_ones_deny_rule(tmp_path):
    (tmp_path / "deny.toml").write_text('[[deny]]\nid = "p.deny"\nwords = ["x"]\nreason = "A denial."\n')
    (tmp_path / "weaken.toml").write_text('disable = ["p.deny"]\n')
    profile = tmp_path / "phone.toml"
    profile.write_text(
        f'[device]\nserial = "{J7_SERIAL}"\nname = "phone"\npolicy_files = ["deny.toml", "weaken.toml"]\n'
    )
    with pytest.raises(Refusal) as refused:
        load_policy((), load_profile(profile))
    assert refused.value.code is ErrorCode.POLICY_INVALID and refused.value.details["rule"] == "p.deny"


def test_a_caller_file_may_still_disable_a_deny_rule_that_another_caller_file_defines(tmp_path):
    (tmp_path / "deny.toml").write_text('[[deny]]\nid = "c.deny"\nwords = ["x"]\nreason = "A denial."\n')
    (tmp_path / "weaken.toml").write_text('disable = ["c.deny"]\n')
    install_j7(tmp_path)
    loaded = profile_for(load_profiles(tmp_path), J7_SERIAL)
    policy = load_policy([tmp_path / "deny.toml", tmp_path / "weaken.toml"], loaded)
    assert "c.deny" not in {rule.origin.rule for rule in policy.rules}
