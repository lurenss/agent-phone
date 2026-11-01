"""The verification skill's `evidence.py` runs reads as given and refuses anything that may change
the phone unless the caller claims it as an input. A protected package is refused even then."""

import argparse
import importlib.util
import json

import pytest
from support import ROOT

SCRIPT = ROOT / ".claude" / "skills" / "verify-agent-phone" / "scripts" / "evidence.py"
spec = importlib.util.spec_from_file_location("evidence", SCRIPT)
evidence = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evidence)

READS = [
    ["agent-phone", "snapshot", "--settle"],
    ["agent-phone", "-d", "0a1b2c3d4e5f6a7b", "find", "--name", "Wi-Fi"],
    ["agent-phone", "server", "stop"],
    ["adb", "-s", "0a1b2c3d4e5f6a7b", "shell", "dumpsys window | grep mCurrentFocus"],
    ["adb", "shell", "getprop ro.build.version.sdk; wm size; cat /proc/sys/kernel/random/boot_id"],
    ["adb", "shell", "pgrep -f 'uia2[.]Main' || echo none"],
    ["adb", "shell", "uiautomator dump /dev/null 2>&1"],
    ["adb", "exec-out", "screencap", "-p"],
    ["adb", "devices", "-l"],
    ["agent-phone", "screenshot"],
    ["agent-phone", "clipboard", "get"],
]
CHANGES = [
    ["agent-phone", "click", "@k3x9q:e1"],
    ["agent-phone", "clipboard", "set", "x"],
    ["agent-phone", "stop", "com.android.settings"],
    ["adb", "-s", "0a1b2c3d4e5f6a7b", "shell", "am start -a android.settings.SETTINGS"],
    ["adb", "shell", "input", "keyevent", "KEYCODE_HOME"],
    ["adb", "shell", "getprop ro.product.model; input tap 10 10"],
    ["adb", "shell", "dumpsys window & input tap 10 10"],
    ["adb", "shell", "settings put global bluetooth_on 1"],
    ["adb", "shell", "wm size 720x1280"],
    ["adb", "shell", "monkey -p com.android.settings 1"],
    ["adb", "reboot"],
    ["python", "-c", "print(1)"],
]


@pytest.mark.parametrize("argv", READS)
def test_a_read_runs_without_the_input_claim(argv):
    assert evidence.is_read(argv)


@pytest.mark.parametrize("argv", CHANGES)
def test_anything_that_may_change_the_phone_needs_the_input_claim(argv):
    assert not evidence.is_read(argv)


def request(run, command, claimed):
    return argparse.Namespace(
        run=str(run), label="step", command=command, input=claimed, env=[], out=None, timeout=1
    )


def test_an_unclaimed_input_and_a_protected_package_are_refused_before_anything_runs(tmp_path):
    with pytest.raises(SystemExit, match="may change the phone"):
        evidence.record(request(tmp_path, ["adb", "shell", "am start -a android.settings.SETTINGS"], False))
    for script in ("am force-stop hev.sockstun", "pkill -f 'hev[.]sockstun'"):
        with pytest.raises(SystemExit, match="protected package"):
            evidence.record(request(tmp_path, ["adb", "shell", script], True))
    assert list(tmp_path.iterdir()) == []


def test_a_record_is_never_overwritten(tmp_path):
    (tmp_path / "step.json").write_text("{}")
    with pytest.raises(SystemExit, match="never overwritten"):
        evidence.record(request(tmp_path, ["agent-phone", "devices"], False))
    assert (tmp_path / "step.json").read_text() == "{}"


def test_flags_before_the_double_dash_are_ours_and_the_rest_is_the_command(tmp_path, capsys):
    with pytest.raises(SystemExit, match="protected package"):
        evidence.main(
            ["run", str(tmp_path), "stop-vpn", "--input", "--", "adb", "shell", "am force-stop hev.sockstun"]
        )
    with pytest.raises(SystemExit, match="may change the phone"):
        evidence.main(["run", str(tmp_path), "open", "--", "adb", "shell", "am", "start", "--input"])
    code = evidence.main(
        ["run", str(tmp_path), "say", "--input", "--env", "X=1", "--", "python", "-c", "print('hi')"]
    )
    entry = json.loads((tmp_path / "say.json").read_text())
    assert code == 0 and capsys.readouterr().out == "hi\n"
    assert (
        entry["input"] is True
        and entry["env"] == {"X": "1"}
        and entry["argv"] == ["python", "-c", "print('hi')"]
    )
    assert entry["exit"] == 0 and entry["stdout"] == "hi\n"
