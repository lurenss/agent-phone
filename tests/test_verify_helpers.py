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
    ["agent-phone", "wait", "--for", "name=Brightness", "--timeout-ms", "1500"],
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


def test_the_words_judged_for_a_protected_package_include_the_steps_in_a_batch_file(tmp_path):
    steps = tmp_path / "steps.json"
    steps.write_text('[["launch", "com.android.settings"], ["stop", "hev.sockstun"]]')
    for argv in (
        ["agent-phone", "batch", str(steps)],
        ["agent-phone", "-d", "0a1b2c3d4e5f6a7b", "batch", str(steps)],
        ["agent-phone", "batch", "-d", "0a1b2c3d4e5f6a7b", str(steps)],
    ):
        assert "hev.sockstun" in evidence.scanned(argv)
    assert "hev.sockstun" not in evidence.scanned(["agent-phone", "batch", str(tmp_path / "nowhere.json")])
    assert "hev.sockstun" not in evidence.scanned(["agent-phone", "snapshot"])


def test_a_batch_that_names_a_protected_package_in_its_steps_is_refused_before_it_runs(tmp_path, monkeypatch):
    def never(*args, **kwargs):
        raise AssertionError("the batch reached the phone")

    monkeypatch.setattr(evidence.subprocess, "run", never)
    steps = tmp_path / "steps.json"
    steps.write_text('[["stop", "hev.sockstun"]]')
    run = tmp_path / "run"
    run.mkdir()
    with pytest.raises(SystemExit, match="protected package"):
        evidence.record(request(run, ["agent-phone", "batch", str(steps)], True))
    with pytest.raises(SystemExit, match="steps file"):
        evidence.record(request(run, ["agent-phone", "batch"], True))
    with pytest.raises(SystemExit, match="may change the phone"):
        evidence.record(request(run, ["agent-phone", "batch", str(steps)], False))
    assert list(run.iterdir()) == []


def test_list_skips_a_batch_steps_file_kept_in_the_run_folder(tmp_path, capsys):
    (tmp_path / "three-steps.json").write_text('[["press", "back"]]')
    record = {
        "label": "batch",
        "argv": ["agent-phone", "batch", str(tmp_path / "three-steps.json")],
        "input": True,
        "started_utc": "2026-11-01T04:30:06.436+00:00",
        "ms": 2843,
        "exit": 0,
    }
    (tmp_path / "batch.json").write_text(json.dumps(record))
    assert evidence.listing(str(tmp_path)) == 0
    out = capsys.readouterr().out
    assert "1 records, 1 inputs" in out and "input: agent-phone batch" in out


DOCTOR = ROOT / ".claude" / "skills" / "verify-agent-phone" / "scripts" / "doctor.py"
doctor_spec = importlib.util.spec_from_file_location("doctor", DOCTOR)
doctor = importlib.util.module_from_spec(doctor_spec)
doctor_spec.loader.exec_module(doctor)

TWO_SCREENS = """WINDOW MANAGER DISPLAY CONTENTS (dumpsys window displays)
  Display: mDisplayId=4 (organized)
    init=1080x1240 369dpi
  mCurrentFocus=Window{310cce3 u0 primaryScreenTopLayout}
  mFocusedApp=ActivityRecord{31a00e4 u0 com.android.launcher3/.SecondaryDisplayLauncher} t147}
  Display: mDisplayId=0 (organized)
    init=1080x1920 369dpi
  mCurrentFocus=Window{4e4f68d u0 com.android.launcher3/com.android.launcher3.uioverrides.QuickstepLauncher}
"""


def test_the_doctor_names_the_focus_of_display_0_when_another_screen_is_listed_first():
    focus = doctor.display_focus(TWO_SCREENS)
    assert focus is not None and focus.endswith("uioverrides.QuickstepLauncher}")


def test_the_doctor_says_so_when_display_0_has_no_focus_line():
    assert doctor.display_focus(TWO_SCREENS.split("  Display: mDisplayId=0")[0]) is None


THOR_PS = """  PID NAME
29769 dev.eden.eden_emulator
29822 dev.eden.eden_emulator.nightly
14361 hev.sockstun:native
"""


def test_the_doctor_finds_a_package_and_its_named_processes_and_no_package_that_extends_it():
    assert doctor.pids_of(THOR_PS, "dev.eden.eden_emulator") == ["29769"]
    assert doctor.pids_of(THOR_PS, "dev.eden.eden_emulator.nightly") == ["29822"]
    assert doctor.pids_of(THOR_PS, "hev.sockstun") == ["14361"]
    assert doctor.pids_of(THOR_PS, "hev.socks") == []
