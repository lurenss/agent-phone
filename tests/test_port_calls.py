"""Every phone call of the port scripts goes through `Recorder`, which runs evidence.py. These
tests run the real evidence.py against a fake phone, so what it refuses here is what it refuses
on a device."""

import json

import pytest
from port_support import FakePhone, Screen, shared

calls = shared("device_calls")


def phone() -> FakePhone:
    return FakePhone(screens={"home": Screen("com.android.launcher3")}, screen="home")


def recorder(tmp_path, fake=None) -> calls.Recorder:
    return calls.Recorder(tmp_path, "S1", (fake or phone()).runner)


def test_a_read_is_recorded_without_the_input_claim_and_an_input_with_it(tmp_path):
    fake = phone()
    rec = recorder(tmp_path, fake)
    rec.read("look", "snapshot")
    rec.send("home", "press", "home")
    looked, sent = (json.loads((tmp_path / f"{n}.json").read_text()) for n in ("look", "home"))
    assert looked["input"] is False and sent["input"] is True
    assert sent["argv"] == ["agent-phone", "-d", "S1", "press", "home"]
    assert rec.sent == ["agent-phone -d S1 press home"]


def test_an_input_is_preceded_by_a_read_when_none_happened_since_the_last_input(tmp_path):
    fake = phone()
    rec = recorder(tmp_path, fake)
    rec.send("home", "press", "home")
    rec.send("again", "press", "home")
    assert [c[0] for c in fake.commands] == ["snapshot", "press", "snapshot", "press"]
    assert fake.inputs == [("press", "home"), ("press", "home")]


def test_an_input_right_after_a_read_needs_no_extra_look(tmp_path):
    fake = phone()
    rec = recorder(tmp_path, fake)
    rec.read("seen", "snapshot", "--settle")
    rec.send("home", "press", "home")
    assert [c[0] for c in fake.commands] == ["snapshot", "press"]


def test_a_wait_that_timed_out_is_not_an_observation(tmp_path):
    fake = phone()
    rec = recorder(tmp_path, fake)
    assert rec.read("late", "wait", "--app", "other.app").error_code == "TIMEOUT"
    rec.send("home", "press", "home")
    assert [c[0] for c in fake.commands] == ["wait", "snapshot", "press"]


def test_a_failed_look_is_tried_three_times_and_then_no_input_goes_out(tmp_path):
    fake = phone()
    fake.snapshot_failures = 2
    rec = recorder(tmp_path, fake)
    rec.send("home", "press", "home")
    assert fake.inputs == [("press", "home")]
    fake.snapshot_failures = 3
    with pytest.raises(calls.ObserveFailed):
        rec.send("again", "press", "home")
    assert fake.inputs == [("press", "home")]


def test_a_label_that_exists_in_the_run_folder_gets_a_number_not_an_overwrite(tmp_path):
    first = recorder(tmp_path)
    first.read("look", "snapshot")
    second = recorder(tmp_path)
    second.read("look", "snapshot")
    second.read("look", "snapshot")
    assert sorted(p.stem for p in tmp_path.glob("*.json")) == ["look", "look-2", "look-3"]


def test_evidence_refuses_a_protected_package_and_the_script_hears_of_it(tmp_path):
    fake = phone()
    rec = recorder(tmp_path, fake)
    rec.read("seen", "snapshot")
    with pytest.raises(calls.EvidenceRefused, match="protected package"):
        rec.send("vpn", "launch", "hev.sockstun")
    assert fake.inputs == [] and rec.sent == []


def test_a_command_that_is_not_a_known_read_is_refused_without_the_input_claim(tmp_path):
    rec = recorder(tmp_path)
    with pytest.raises(calls.EvidenceRefused, match="may change the phone"):
        rec.adb("tap", "shell", "input", "tap", "1", "1")
    with pytest.raises(calls.EvidenceRefused, match="may change the phone"):
        rec.call("clear", ["adb", "-s", "S1", "logcat", "-c"])


def test_the_raw_dump_goes_through_evidence_as_a_read(tmp_path):
    fake = phone()
    rec = recorder(tmp_path, fake)
    call = rec.raw_dump("dump", "x-launcher")
    assert fake.dumps == ["x-launcher"] and "12 nodes" in call.text
    assert json.loads((tmp_path / "dump.json").read_text())["input"] is False


def test_a_json_looking_output_comes_back_as_its_text(tmp_path):
    fake = phone()
    fake.shell["settings get global bluetooth_on"] = "0\n"
    call = recorder(tmp_path, fake).adb("bt", "shell", "settings", "get", "global", "bluetooth_on")
    assert call.text == "0"


def test_the_journal_writes_and_prints_one_line_per_check(tmp_path, capsys):
    journal = calls.Journal(tmp_path / "survey.jsonl")
    journal.emit(check="a", n=1)
    journal.emit(check="b", text="é")
    lines = (tmp_path / "survey.jsonl").read_text().splitlines()
    assert [json.loads(line)["check"] for line in lines] == ["a", "b"]
    assert capsys.readouterr().out.splitlines() == lines
    assert calls.Journal(tmp_path / "survey.jsonl") and (tmp_path / "survey.jsonl").read_text() == ""
