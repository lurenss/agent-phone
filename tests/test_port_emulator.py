"""emulator.py boots an emulator and waits until it is booted: boot_completed, the requested locale
and a focus that is not FallbackHome, all on one poll. The fake adb follows the order a real boot
takes, on a clock that moves only when the script waits, so a test never sleeps."""

import io
import subprocess

import pytest
from port_support import script
from support import FakeClock

emulator = script("emulator")

LAUNCHER = "mCurrentFocus=Window{4e4f68d u0 com.google.android.apps.nexuslauncher/.NexusLauncherActivity}"
FALLBACK = "mCurrentFocus=Window{9a1b u0 com.android.settings/.FallbackHome}"
NO_SERVICE = "Can't find service: window"


def done(argv, out="", code=0):
    return subprocess.CompletedProcess(argv, code, out, "")


class FakeEmulator:
    """The phone side of a boot, by the time since the process started: offline, then the kernel is up,
    then boot_completed with the locale not applied and the framework restarting, then FallbackHome,
    then the launcher."""

    def __init__(self, clock, started_at=0.0, locale="it-IT"):
        self.clock, self.started_at, self.locale, self.calls = clock, started_at, locale, []
        self.started = False

    def seconds(self) -> float:
        return self.clock.time - self.started_at

    def __call__(self, argv, **kwargs):
        self.calls.append(argv)
        if argv[-1] == "get-state":
            return done(argv, "device\n") if self.started and self.seconds() >= 20 else done(argv, "", 1)
        if argv[-1] == "kill":
            return done(argv, "OK: killing emulator, bye bye\n")
        words = argv[4:]
        t = self.seconds()
        if not self.started or t < 20:
            return done(argv, "", 1)
        if words == ["getprop", "sys.boot_completed"]:
            return done(argv, "1\n" if t >= 30 else "0\n")
        if words == ["getprop", "persist.sys.locale"]:
            return done(argv, f"{self.locale}\n" if t >= 45 else "en-US\n")
        assert words == ["dumpsys", "window"], words
        if t < 45:
            return done(argv, NO_SERVICE + "\n")
        return done(argv, FALLBACK + "\n" if t < 60 else LAUNCHER + "\n")


class FakeProcess:
    def __init__(self, clock, exits_at=None, code=1):
        self.clock, self.exits_at, self.code = clock, exits_at, code

    def poll(self):
        return self.code if self.exits_at is not None and self.clock.time >= self.exits_at else None


@pytest.fixture
def sdk(tmp_path):
    root = tmp_path / "sdk"
    (root / "emulator").mkdir(parents=True)
    (root / "emulator" / "emulator").write_text("#!/bin/sh\n")
    (root / "platform-tools").mkdir()
    return root


def boot(tmp_path, sdk, *extra, exits_at=None, applied="it-IT", requested="it-IT", clock=None):
    clock = clock or FakeClock()
    adb = FakeEmulator(clock, locale=applied)
    launched = []

    def launch(command, log):
        adb.started = True
        adb.started_at = clock.time
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text("emulator: INFO: boot\nemulator: ERROR: something broke\n")
        launched.append((command, log))
        return FakeProcess(clock, None if exits_at is None else clock.time + exits_at)

    env = {"ANDROID_HOME": str(sdk), "AGENT_PHONE_HOME": str(tmp_path / "state")}
    out = io.StringIO()
    argv = ["boot", "--avd", "ap-de-35", "--locale", requested, *extra]
    code = emulator.main(argv, adb, launch, clock, out, env)
    return code, out.getvalue(), launched, adb, clock


def test_the_emulator_is_started_with_the_documented_flags_and_its_log_in_the_state_root(tmp_path, sdk):
    _, _, launched, _, _ = boot(tmp_path, sdk)
    ((command, log),) = launched
    assert command == [
        str(sdk / "emulator" / "emulator"),
        "-avd", "ap-de-35", "-no-window", "-no-audio", "-no-boot-anim", "-no-snapshot",
        "-change-locale", "it-IT", "-port", "5554",
    ]  # fmt: skip
    assert log == tmp_path / "state" / "emulators" / "ap-de-35-5554.log"


def test_it_prints_the_serial_and_only_the_serial_once_all_three_conditions_hold_on_one_poll(tmp_path, sdk):
    code, out, _, adb, clock = boot(tmp_path, sdk)
    assert code == 0 and out == "emulator-5554\n"
    assert 60 <= clock.time < 60 + emulator.POLL_GAP_S, "boot_completed alone, at 30 s, was not enough"
    assert set(clock.pauses) == {emulator.POLL_GAP_S}


def test_boot_completed_with_the_wrong_locale_or_the_framework_restarting_is_not_booted():
    clock = FakeClock()
    adb = FakeEmulator(clock)
    adb.started = True
    for seconds, expected in ((10, False), (25, False), (35, False), (50, False), (61, True)):
        clock.time = seconds
        assert emulator.booted(adb, "emulator-5554", "it-IT") is expected, seconds
    clock.time = 35
    assert emulator.booted(adb, "emulator-5554", None) is False, "the window service is still down"
    adb.locale = "en-US"
    clock.time = 70
    assert emulator.booted(adb, "emulator-5554", "it-IT") is False, (
        "the launcher is up, the locale is not applied"
    )
    assert emulator.booted(adb, "emulator-5554", None) is True, "with no locale asked for, none is checked"
    adb.locale = "it_IT"
    clock.time = 70
    assert emulator.booted(adb, "emulator-5554", "it-IT") is True, "persist.sys.locale may use an underscore"


@pytest.mark.parametrize(
    ("text", "ready"),
    [
        (NO_SERVICE, False),
        ("", False),
        ("mCurrentFocus=null", False),
        (FALLBACK, False),
        (LAUNCHER, True),
        (f"mCurrentFocus=null\n{LAUNCHER}", True),
        (f"{LAUNCHER}\n  {FALLBACK}", False),
    ],
)
def test_a_focus_that_names_a_window_other_than_fallbackhome_is_ready(text, ready):
    assert emulator.window_ready(text) is ready


def test_it_gives_up_at_the_deadline_and_leaves_the_emulator_running_with_the_way_to_stop_it(
    tmp_path, sdk, capsys
):
    with pytest.raises(SystemExit) as stop:
        boot(tmp_path, sdk, "--deadline-s", "40")
    message = str(stop.value)
    assert "did not finish booting within 40 s" in message and "still running" in message
    assert "emulator.py stop --serial emulator-5554" in message and "ap-de-35-5554.log" in message


def test_the_default_deadline_is_240_seconds_and_a_boot_that_never_ends_stops_waiting_there(tmp_path, sdk):
    assert emulator.BOOT_DEADLINE_S == 240
    clock = FakeClock()
    with pytest.raises(SystemExit, match="within 240 s"):
        boot(tmp_path, sdk, clock=clock, applied="fr-FR")
    assert 240 <= clock.time < 240 + emulator.POLL_GAP_S


def test_an_emulator_that_exits_early_fails_at_once_with_the_end_of_its_log(tmp_path, sdk):
    clock = FakeClock()
    with pytest.raises(SystemExit) as stop:
        boot(tmp_path, sdk, exits_at=7, clock=clock)
    assert "exited with code 1" in str(stop.value) and "something broke" in str(stop.value)
    assert clock.time < 12


def test_a_missing_platform_tools_folder_is_refused_with_the_fix_and_is_not_made(tmp_path, sdk):
    (sdk / "platform-tools").rmdir()
    with pytest.raises(SystemExit) as stop:
        boot(tmp_path, sdk)
    message = str(stop.value)
    assert "platform-tools is missing" in message and "Broken AVD system path" in message
    assert (
        f"mkdir -p {sdk}/platform-tools" in message and "ln -s" in message and "does not make it" in message
    )
    assert not (sdk / "platform-tools").exists()


def test_a_missing_emulator_binary_is_refused_before_anything_starts(tmp_path, sdk):
    (sdk / "emulator" / "emulator").unlink()
    with pytest.raises(SystemExit, match="Set ANDROID_HOME"):
        boot(tmp_path, sdk)
    assert not (tmp_path / "state").exists()


def test_a_port_that_has_an_emulator_already_is_refused_and_nothing_is_started(tmp_path, sdk):
    def busy(argv, **kwargs):
        return done(argv, "device\n")

    started = []
    env = {"ANDROID_HOME": str(sdk), "AGENT_PHONE_HOME": str(tmp_path)}
    argv = ["boot", "--avd", "a", "--locale", "en-US"]
    with pytest.raises(SystemExit, match="emulator-5554 is running already"):
        emulator.main(argv, busy, lambda *a: started.append(a), FakeClock(), io.StringIO(), env)
    assert started == []


def test_another_port_gives_another_serial_and_log(tmp_path, sdk):
    code, out, launched, _, _ = boot(tmp_path, sdk, "--port", "5556")
    assert out == "emulator-5556\n" and launched[0][0][-2:] == ["-port", "5556"]
    assert launched[0][1].name == "ap-de-35-5556.log"


def test_the_sdk_defaults_to_the_android_studio_folder_and_android_home_overrides_it():
    assert str(emulator.sdk_root({})).endswith("Library/Android/sdk")
    assert str(emulator.sdk_root({"ANDROID_HOME": ""})).endswith("Library/Android/sdk")
    assert str(emulator.sdk_root({"ANDROID_HOME": "/opt/sdk"})) == "/opt/sdk"


@pytest.mark.parametrize(
    "argv",
    [
        ["boot", "--avd", "a", "--locale", "it"],
        ["boot", "--avd", "a", "--locale", "it_IT"],
        ["boot", "--avd", "a", "--locale", "en-US", "--port", "5555"],
        ["boot", "--avd", "a", "--locale", "en-US", "--port", "9999"],
        ["boot", "--avd", "a"],
        ["stop", "--serial", "0a1b2c3d4e5f6a7b"],
        ["stop", "--serial", "emulator-5554; rm"],
    ],
)
def test_arguments_that_could_start_the_wrong_thing_or_stop_a_real_phone_are_refused(argv):
    with pytest.raises(SystemExit) as stop:
        emulator.main(argv, lambda *a, **k: pytest.fail("adb ran"), lambda *a: pytest.fail("started"))
    assert stop.value.code == 2


def test_stop_kills_the_emulator_through_adb_and_prints_what_adb_said():
    calls, out = [], io.StringIO()

    def adb(argv, **kwargs):
        calls.append(argv)
        return done(argv, "OK: killing emulator, bye bye\n")

    assert emulator.main(["stop", "--serial", "emulator-5554"], adb, out=out) == 0
    assert calls == [["adb", "-s", "emulator-5554", "emu", "kill"]]
    assert out.getvalue() == "OK: killing emulator, bye bye\n"


def test_stop_returns_adbs_exit_code_when_the_emulator_is_not_there():
    out = io.StringIO()
    code = emulator.main(["stop", "--serial", "emulator-5560"], lambda argv, **k: done(argv, "", 1), out=out)
    assert code == 1
