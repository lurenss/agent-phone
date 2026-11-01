"""Test support for the port-android-device scripts: a loader for them, and a phone that sits behind
the real `evidence.py`. A script talks to `FakePhone` the way it talks to a device: through
`Recorder`, which runs `evidence.py`, which runs the command. Only the last step is replaced, so
evidence.py's own checks (a read needs no `--input`, an input does, a protected package is refused)
run for real, and so do the records the scripts read back. The fake also refuses an input that has
no read since the last input (`OBSERVE_FIRST`), as agent-phone does."""

import contextlib
import importlib
import importlib.util
import io
import json
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from unittest import mock

from support import ROOT

SKILL = ROOT / ".claude" / "skills" / "port-android-device" / "scripts"
if str(SKILL) not in sys.path:
    sys.path.append(str(SKILL))


def shared(name: str):
    """A module the scripts import by name, such as `device_calls`."""
    return importlib.import_module(name)


def script(name: str):
    """A script of the skill, loaded by path under the name `port_<name>`, so a script called
    `profile` never shadows the standard library's."""
    module_name = f"port_{name}"
    if module_name in sys.modules:
        return sys.modules[module_name]
    spec = importlib.util.spec_from_file_location(module_name, SKILL / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


EVIDENCE = ROOT / ".claude" / "skills" / "verify-agent-phone" / "scripts" / "evidence.py"
evidence_spec = importlib.util.spec_from_file_location("port_evidence", EVIDENCE)
evidence = importlib.util.module_from_spec(evidence_spec)
evidence_spec.loader.exec_module(evidence)


COLLECTIONS = ("scroll", "list", "grid", "pager")


@dataclass(frozen=True)
class Screen:
    """What `snapshot` says about one screen of the fake phone."""

    app: str
    tree: tuple[str, ...] = ('button "OK" [0,0,10,10]',)
    dialog: bool = False
    window: str = "application"


def envelope(command: str, serial: str, **fields: object) -> dict:
    return {"v": 1, "ok": True, "command": command, "permission_mode": "ask", "device": serial} | fields


def refusal(command: str, serial: str, code: str, delivery: str = "not_delivered") -> dict:
    retry = "safe" if delivery == "not_delivered" else "unsafe"
    error = {"code": code, "message": "canned", "hint": None, "details": {}}
    return envelope(command, serial, ok=False, delivery=delivery, retry=retry, error=error)


@dataclass
class FakePhone:
    """`react(words)` is the phone's behavior: it maps an input, given as the words after `-d SERIAL`,
    to the next screen name, or raises `Refused` with an error code. The default does nothing."""

    serial: str = "S1"
    screens: dict[str, Screen] = field(default_factory=dict)
    screen: str = ""
    shell: dict[str, str] = field(default_factory=dict)
    react: Callable[["FakePhone", tuple[str, ...]], str] | None = None
    focus: Callable[["FakePhone"], str | None] | None = None
    epoch: int = 0
    observed: int | None = None
    commands: list[tuple[str, ...]] = field(default_factory=list)
    inputs: list[tuple[str, ...]] = field(default_factory=list)
    dumps: list[str] = field(default_factory=list)
    snapshot_failures: int = 0
    raw_dir: Path | None = None
    raw_xml: Callable[["FakePhone"], str] | None = None

    class Refused(Exception):
        def __init__(self, code: str) -> None:
            self.code = code

    @property
    def current(self) -> Screen:
        return self.screens[self.screen]

    def runner(self, command: list[str], **kwargs) -> subprocess.CompletedProcess:
        """Stands in for `subprocess.run` of `Recorder`: runs the real evidence.py in this process."""
        out = io.StringIO()
        with (
            mock.patch.object(evidence.subprocess, "run", self.execute),
            contextlib.redirect_stdout(out),
        ):
            try:
                code = evidence.main(command[3:])
            except SystemExit as stop:
                return subprocess.CompletedProcess(command, 1, "", str(stop.code))
        return subprocess.CompletedProcess(command, code, out.getvalue(), "")

    def execute(self, argv: list[str], **kwargs) -> subprocess.CompletedProcess:
        name = Path(argv[0]).name
        if name == "agent-phone":
            words = tuple(argv[1:])
            assert words[:2] == ("-d", self.serial), words
            out = json.dumps(self.agent_phone(words[2:]))
        elif name == "adb":
            assert argv[1:3] == ["-s", self.serial], argv
            out = self.adb(argv[3:])
        else:
            assert argv[1].endswith("raw_dump.py"), argv
            self.dumps.append(argv[3])
            if self.raw_dir is not None and self.raw_xml is not None:
                (self.raw_dir / f"{argv[3]}.raw.xml").write_text(self.raw_xml(self))
            out = f"/raw/{argv[3]}.raw.xml 12 nodes\n"
        return subprocess.CompletedProcess(argv, 0, out.encode(), b"")

    def adb(self, words: list[str]) -> str:
        assert words[0] in ("shell", "logcat"), words
        script = " ".join(words[1:])
        if script == "dumpsys window displays" and script not in self.shell:
            return self.window_dump()
        return self.shell.get(script, "")

    def window_dump(self) -> str:
        owner = self.focus(self) if self.focus else self.current.app
        line = (
            "mCurrentFocus=null"
            if owner is None
            else f"mCurrentFocus=Window{{4e4f68d u0 {owner}/{owner}.Main}}"
        )
        return (
            "WINDOW MANAGER DISPLAY CONTENTS (dumpsys window displays)\n"
            "  Display: mDisplayId=0 (organized)\n"
            "    init=1080x1920 420dpi\n"
            f"  {line}\n"
            "  mTopFocusedDisplayId=0\n"
        )

    def agent_phone(self, words: tuple[str, ...]) -> dict:
        self.commands.append(words)
        command = words[0]
        if command in ("snapshot", "wait"):
            return self.observe(command, words)
        if command in ("press", "open-url", "scroll", "launch"):
            return self.act(command, words)
        raise AssertionError(f"the fake phone has no {command}")

    def observe(self, command: str, words: tuple[str, ...]) -> dict:
        if self.snapshot_failures:
            self.snapshot_failures -= 1
            return refusal(command, self.serial, "TRANSPORT")
        screen = self.current
        if command == "wait" and not self.wait_holds(words, screen):
            return refusal(command, self.serial, "TIMEOUT")
        self.observed = self.epoch
        settled = "settled" if "--settle" in words or "--settled" in words else "unchecked"
        data = {
            "id": f"s{self.epoch:04d}",
            "app": screen.app,
            "window": screen.window,
            "mode": "compact",
            "settled": settled,
            "keyboard": False,
            "dialog": screen.dialog,
            "others": [],
            "toasts": [],
            "truncated": 0,
            "tree": [f"@s{self.epoch:04d}:e{i} {line}" for i, line in enumerate(screen.tree, 1)],
        }
        return envelope(command, self.serial, data=data)

    def wait_holds(self, words: tuple[str, ...], screen: Screen) -> bool:
        app = words[words.index("--app") + 1] if "--app" in words else screen.app
        wants_button = "--for" in words and words[words.index("--for") + 1] == "role=button"
        return screen.app == app and (not wants_button or any(" button " in f" {t}" for t in screen.tree))

    def scrollers(self) -> list[str]:
        """The refs of the collections on the current screen, as its last snapshot printed them."""
        return [
            f"@s{self.epoch:04d}:e{i}"
            for i, line in enumerate(self.current.tree, 1)
            if line.split(" ")[0] in COLLECTIONS
        ]

    def check_scroll_target(self, words: tuple[str, ...]) -> None:
        """How `scroll DIRECTION [TARGET]` finds its collection: with no target, the only one on the
        screen, and two are `AMBIGUOUS_TARGET`. A ref of an earlier snapshot is `STALE_REF`."""
        found = self.scrollers()
        if len(words) < 3:
            if len(found) != 1:
                raise FakePhone.Refused("AMBIGUOUS_TARGET" if found else "NOT_FOUND")
        elif words[2] not in found:
            raise FakePhone.Refused(
                "NOT_ACTIONABLE" if words[2].startswith(f"@s{self.epoch:04d}:") else "STALE_REF"
            )

    def act(self, command: str, words: tuple[str, ...]) -> dict:
        if self.observed != self.epoch:
            return refusal(command, self.serial, "OBSERVE_FIRST")
        try:
            if command == "scroll":
                self.check_scroll_target(words)
            self.screen = self.react(self, words) if self.react else self.screen
        except FakePhone.Refused as refused:
            return refusal(command, self.serial, refused.code)
        self.epoch += 1
        self.inputs.append(words)
        data = {"input": {"kind": command}, "target": None, "gate": {"verdict": "clear"}, "verified_by": None}
        return envelope(command, self.serial, delivery="delivered_unverified", retry="unsafe", data=data)
