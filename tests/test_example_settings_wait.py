"""examples/settings_wait.py on a scripted phone: each input moves the screen on to its next
phase, and the first read of a phase can still show the one before it, as a real phone does
(A2-10). The example must follow that without a sleep, and send exactly the inputs it names."""

import ast
import importlib.util

import pytest
from fakes import J7_SERIAL, FakeHub, FakePhone
from support import ROOT, FakeClock, fixture_screen, node, screen_of

from agent_phone import open_phone
from agent_phone.cli.settings import Settings
from agent_phone.core.device import Connected
from agent_phone.core.phone import Ack, Key, KeyName, Launch, OpenUri, Sent
from agent_phone.core.wait.clock import POLL_GAP_S

EXAMPLE = ROOT / "examples" / "settings_wait.py"
J7 = Connected(J7_SERIAL, "SM_J730F", ready=True)

LAUNCHER = screen_of(
    node(
        "android.widget.FrameLayout",
        node("android.widget.TextView", text="Home screen", bounds="[0,100][1080,200]"),
        package="com.sec.android.app.launcher",
        bounds="[0,0][1080,1920]",
    )
)
SETTINGS_HOME = fixture_screen("settings-home")
DISPLAY_PAGE = screen_of(
    node(
        "android.widget.FrameLayout",
        node("android.widget.TextView", text="Display", bounds="[147,96][337,177]"),
        node(
            "android.widget.LinearLayout",
            node("android.widget.TextView", text="Brightness", bounds="[0,242][1080,392]"),
            node(
                "android.widget.SeekBar",
                text="1764.0",
                resource_id="com.android.settings:id/brightness_seekbar",
                bounds="[147,392][1017,476]",
            ),
            clickable=True,
            bounds="[0,242][1080,536]",
        ),
        package="com.android.settings",
        bounds="[0,0][1080,1920]",
    )
)
PHASES = [
    [LAUNCHER],
    [LAUNCHER, SETTINGS_HOME],
    [SETTINGS_HOME, DISPLAY_PAGE],
    [DISPLAY_PAGE, SETTINGS_HOME],
    [LAUNCHER],
]


class PhasedPhone(FakePhone):
    """Shows the first phase, and each delivered input switches to the next."""

    def __init__(self, info, phases):
        super().__init__(info, *phases[0])
        self._later = list(phases[1:])

    def inject(self, permit):
        self.permits.append(permit)
        if self._later:
            self._screens, self._at = tuple(self._later.pop(0)), 0
        return Sent(Ack.ACKNOWLEDGED, "fake")


class PhasedHub(FakeHub):
    def __init__(self, phases):
        super().__init__([J7])
        self._phases = phases

    def open(self, serial, first_read=False):
        phone = PhasedPhone(self._infos[serial], self._phases)
        self.phones.append(phone)
        return phone


@pytest.fixture
def example():
    spec = importlib.util.spec_from_file_location("settings_wait", EXAMPLE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def session(hub, tmp_path, clock):
    return open_phone(hub=hub, settings=Settings(state_root=tmp_path, lock_wait_s=0.0), clock=clock)


def test_it_opens_the_page_and_reads_the_row_by_waiting_for_each_screen(example, tmp_path):
    hub, clock, steps = PhasedHub(PHASES), FakeClock(), []
    with session(hub, tmp_path, clock) as phone:
        brightness = example.read_display_page(phone, steps)
    assert brightness == "1764.0"
    assert [label for label, _ in steps] == [
        "look first",
        "launch settings",
        "wait: settings in the foreground",
        "open the display page",
        "wait: brightness row",
        "read the brightness slider",
        "press back",
        "wait: display page gone",
        "press home",
    ]
    assert clock.pauses == [POLL_GAP_S] * 3, "each wait read the stale screen once, then the new one"


def test_it_sends_the_four_inputs_it_names_and_nothing_else(example, tmp_path):
    hub = PhasedHub(PHASES)
    with session(hub, tmp_path, FakeClock()) as phone:
        example.read_display_page(phone, [])
    sent = [permit.action for permit in hub.phones[0].permits]
    assert [type(action) for action in sent] == [Launch, OpenUri, Key, Key]
    assert sent[0].package == "com.android.settings"
    assert sent[1].uri == "intent:#Intent;action=android.settings.DISPLAY_SETTINGS;end"
    assert [sent[2].key, sent[3].key] == [KeyName.BACK, KeyName.HOME]


def test_it_prints_the_value_and_one_line_per_step(example, tmp_path, capsys, monkeypatch):
    hub, clock = PhasedHub(PHASES), FakeClock()
    monkeypatch.setattr(example, "open_phone", lambda serial: session(hub, tmp_path, clock), raising=True)
    assert example.main([]) == 0
    printed = capsys.readouterr().out.splitlines()
    assert printed[0] == "brightness slider value: 1764.0"
    assert len(printed) == 1 + 9 + 1 and printed[-1].startswith("total")


def test_a_page_that_never_opens_stops_the_script_with_what_the_screen_showed(
    example, tmp_path, capsys, monkeypatch
):
    stuck = [*PHASES[:2], [SETTINGS_HOME]]
    hub, clock = PhasedHub(stuck), FakeClock()
    monkeypatch.setattr(example, "open_phone", lambda serial: session(hub, tmp_path, clock))
    assert example.main([]) == 1
    seen = capsys.readouterr()
    assert "Brightness" in seen.err and "the last screen showed" in seen.err
    assert [type(p.action) for p in hub.phones[0].permits] == [Launch, OpenUri]


def test_it_uses_the_public_api_and_never_sleeps():
    tree = ast.parse(EXAMPLE.read_text(encoding="utf-8"))
    modules = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    modules |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    ours = {name for name in modules if name and name.split(".")[0] == "agent_phone"}
    assert ours == {"agent_phone"}, f"the example reaches past the public API: {ours}"
    assert "sleep" not in {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
