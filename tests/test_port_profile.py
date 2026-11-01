"""profile.py writes a device profile, installs it into a state root and proves agent-phone loads it.
Every test uses a state root and a devices folder of its own, never the real ones."""

from pathlib import Path

import pytest
from port_support import evidence, script
from support import ROOT

from agent_phone.cli.policy import load_policy, load_profile

profile = script("profile")
CHESS = str(ROOT / "examples" / "chess" / "policy.toml")
INSTAGRAM = str(ROOT / "examples" / "instagram" / "policy.toml")
VPN = "com.vpn.app=Always-on lockdown VPN: stopping it takes the phone offline."


def run(tmp_path, *args):
    argv = ["--serial", "SER1", "--name", "demo", *args]
    return profile.main(argv, tmp_path / "state", tmp_path / "devices")


def written(tmp_path):
    return tmp_path / "devices" / "demo.toml"


def installed(tmp_path):
    return tmp_path / "state" / "profiles" / "demo.toml"


def test_the_profile_agent_phone_loads_is_the_one_that_was_asked_for(tmp_path):
    assert (
        run(tmp_path, "--protect", VPN, "--protect", "com.game=Unsaved progress", "--policy-file", CHESS) == 0
    )
    loaded = load_profile(written(tmp_path))
    assert (loaded.profile.serial, loaded.profile.name) == ("SER1", "demo")
    assert [(p.package, p.reason) for p in loaded.profile.protected] == [
        ("com.vpn.app", "Always-on lockdown VPN: stopping it takes the phone offline."),
        ("com.game", "Unsaved progress"),
    ]
    assert loaded.profile.policy_files == ("../chess/policy.toml",)


def test_it_writes_what_thor_toml_says_for_the_same_asks(tmp_path):
    thor = load_profile(ROOT / "examples" / "devices" / "thor.toml").profile
    run_args = ["--serial", thor.serial, "--name", "thor", "--policy-file", CHESS]
    for package in thor.protected:
        run_args += ["--protect", f"{package.package}={package.reason}"]
    assert profile.main(run_args, tmp_path / "state", tmp_path / "devices") == 0
    made = load_profile(tmp_path / "devices" / "thor.toml").profile
    assert made.policy_files == thor.policy_files
    assert [(p.package, p.reason) for p in made.protected] == [(p.package, p.reason) for p in thor.protected]


def test_the_header_says_where_the_profile_and_each_policy_file_go(tmp_path):
    run(tmp_path, "--policy-file", CHESS, "--policy-file", INSTAGRAM)
    header = [line for line in written(tmp_path).read_text().splitlines() if line.startswith("#")]
    text = "\n".join(header)
    assert "~/.agent-phone/profiles/" in text
    assert "examples/chess/policy.toml -> ~/.agent-phone/chess/policy.toml" in text
    assert "examples/instagram/policy.toml -> ~/.agent-phone/instagram/policy.toml" in text


def test_a_profile_with_no_policy_file_says_so_and_names_none(tmp_path):
    run(tmp_path, "--protect", VPN)
    text = written(tmp_path).read_text()
    assert "names no policy file" in text and "policy_files" not in text
    assert load_profile(written(tmp_path)).profile.policy_files == ()


def test_the_profile_and_each_policy_file_are_installed_where_the_profile_resolves_them(tmp_path):
    run(tmp_path, "--protect", VPN, "--policy-file", CHESS, "--policy-file", INSTAGRAM)
    assert installed(tmp_path).read_bytes() == written(tmp_path).read_bytes()
    loaded = load_profile(installed(tmp_path))
    assert [path.resolve() for path in loaded.policy_files()] == [
        (tmp_path / "state" / "chess" / "policy.toml").resolve(),
        (tmp_path / "state" / "instagram" / "policy.toml").resolve(),
    ]
    sources = [CHESS, INSTAGRAM]
    for path, source in zip(loaded.policy_files(), sources, strict=True):
        assert path.read_bytes() == Path(source).read_bytes()
    assert load_policy([], loaded).rules


def test_the_state_root_is_agent_phones_home_variable_by_default(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_PHONE_HOME", str(tmp_path / "home"))
    assert profile.main(["--serial", "SER1", "--name", "demo"], devices=tmp_path / "devices") == 0
    assert (tmp_path / "home" / "profiles" / "demo.toml").is_file()


def test_it_refuses_to_overwrite_a_profile_without_force_and_replaces_it_with_it(tmp_path):
    assert run(tmp_path) == 0
    with pytest.raises(SystemExit, match="exists. Pass --force"):
        run(tmp_path, "--protect", VPN)
    assert "protected" not in written(tmp_path).read_text()
    assert run(tmp_path, "--protect", VPN, "--force") == 0
    assert "com.vpn.app" in written(tmp_path).read_text() and "com.vpn.app" in installed(tmp_path).read_text()


def test_it_refuses_an_installed_profile_it_did_not_just_write(tmp_path):
    installed(tmp_path).parent.mkdir(parents=True)
    installed(tmp_path).write_text("# someone's own profile\n")
    with pytest.raises(SystemExit, match="is installed already"):
        run(tmp_path)
    assert not written(tmp_path).exists() and installed(tmp_path).read_text() == "# someone's own profile\n"


def test_a_serial_that_another_installed_profile_names_is_refused_even_with_force(tmp_path):
    other = tmp_path / "state" / "profiles" / "other.toml"
    other.parent.mkdir(parents=True)
    other.write_text('[device]\nserial = "SER1"\nname = "other"\n')
    for extra in ([], ["--force"]):
        with pytest.raises(SystemExit, match="other.toml already names the device SER1"):
            run(tmp_path, *extra)
    assert not written(tmp_path).exists() and not installed(tmp_path).exists()


def test_a_different_file_at_a_policy_destination_is_refused_and_the_same_file_is_not(tmp_path):
    target = tmp_path / "state" / "chess" / "policy.toml"
    target.parent.mkdir(parents=True)
    target.write_text("# edited by hand\n")
    with pytest.raises(SystemExit, match="holds a different file"):
        run(tmp_path, "--policy-file", CHESS)
    assert target.read_text() == "# edited by hand\n" and not written(tmp_path).exists()
    assert run(tmp_path, "--policy-file", CHESS, "--force") == 0
    assert target.read_bytes() == Path(CHESS).read_bytes()
    assert run(tmp_path, "--policy-file", CHESS, "--force") == 0


@pytest.mark.parametrize(
    "policy",
    ['languages = ["xx"]\n', "[[commit]]\nid = 5\n", "this is not toml ["],
    ids=["a language the built-in policy lacks", "a malformed rule", "not toml"],
)
def test_a_policy_file_that_agent_phone_refuses_stops_the_run_before_anything_is_written(tmp_path, policy):
    bad = tmp_path / "app" / "policy.toml"
    bad.parent.mkdir()
    bad.write_text(policy)
    with pytest.raises(SystemExit, match="agent-phone refuses"):
        run(tmp_path, "--policy-file", str(bad))
    assert not (tmp_path / "devices").exists() and not (tmp_path / "state").exists()


@pytest.mark.parametrize(
    "args",
    [
        ["--protect", "nopackage"],
        ["--protect", "com.vpn.app="],
        ["--protect", "Not A Package=reason"],
        ["--protect", VPN, "--protect", VPN],
        ["--policy-file", "/no/such/policy.toml"],
        ["--policy-file", CHESS, "--policy-file", CHESS],
    ],
)
def test_arguments_that_make_no_profile_are_refused_by_the_parser(tmp_path, args):
    with pytest.raises(SystemExit) as stop:
        run(tmp_path, *args)
    assert stop.value.code == 2 and not (tmp_path / "devices").exists()


def test_a_name_and_a_serial_that_could_name_a_path_or_a_flag_are_refused(tmp_path):
    for argv in (["--serial", "S", "--name", "../x"], ["--serial", "a b", "--name", "demo"]):
        with pytest.raises(SystemExit) as stop:
            profile.main(argv, tmp_path / "state", tmp_path / "devices")
        assert stop.value.code == 2


def test_the_protections_it_writes_are_the_ones_evidence_py_refuses_inputs_for(tmp_path, monkeypatch):
    run(tmp_path, "--protect", VPN, "--protect", "com.game=Unsaved progress")
    monkeypatch.setattr(evidence, "PROFILES", tmp_path / "devices")
    assert evidence.protected_packages() == {"com.vpn.app", "com.game"}
