"""Fakes for the remote adapter. `FakeLink` answers a `Claim` from a list. `FakeSsh` stands where
the `ssh` binary does and hands each request to the real `host/phone_host.py`, so the hub tests run
the adapter against the script it will meet."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from host_support import FakeAdbServer, call_host, load_script
from support import fixture_xml

from agent_phone.adapters.remote.link import Done
from agent_phone.adapters.uiautomator2 import server as lifetime
from agent_phone.adapters.uiautomator2.adb import AdbResult
from agent_phone.adapters.uiautomator2.phone import DUMP_METHOD
from agent_phone.core.outcome import Refusal

FACTS = (Path(__file__).parent / "fixtures" / "adb" / "facts-j7.txt").read_text()


def lease(by: str, task: str, free_in_s: int, mine: bool) -> dict[str, object]:
    return {"by": by, "task": task, "held_s": 0, "free_in_s": free_in_s, "mine": mine}


def granted(tenure: str = "t1", port: int = 41001, task: str = "snapshot") -> dict[str, object]:
    return {"v": 1, "ok": True, "id": tenure, "port": port, "lease": lease("ada", task, 120, True)}


def busy(by: str = "ben", task: str = "schedule reel 12", free_in_s: int = 95) -> dict[str, object]:
    return {"v": 1, "ok": False, "error": "busy", "lease": lease(by, task, free_in_s, False)}


class FakeLink:
    def __init__(self, *answers: dict[str, object] | Refusal) -> None:
        self.answers = list(answers)
        self.asked: list[tuple[str, ...]] = []
        self.forwarded: list[int] = []
        self.refreshed = 0

    def ask(self, words):
        self.asked.append(tuple(words))
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(answer, Refusal):
            raise answer
        return answer

    def forward(self, host_port: int) -> int:
        self.forwarded.append(host_port)
        return 50000 + len(self.forwarded)

    def refresh(self) -> None:
        self.refreshed += 1


class Wall:
    def __init__(self) -> None:
        self.time = 1_000_000.0

    def __call__(self) -> float:
        return self.time


class DeviceServer(BaseHTTPRequestHandler):
    inputs: list[str] = []

    def log_message(self, *args):
        pass

    def do_GET(self):
        self._send(b"pong")

    def do_POST(self):
        method = json.loads(self.rfile.read(int(self.headers["Content-Length"])))["method"]
        if method != DUMP_METHOD:
            self.inputs.append(method)
        result = fixture_xml("settings-home") if method == DUMP_METHOD else True
        self._send(json.dumps({"result": result}).encode())

    def _send(self, body: bytes) -> None:
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class FakeSsh:
    def __init__(self, state: Path, adb: FakeAdbServer, who: str = "ada") -> None:
        self._state, self._adb, self._who = state, adb, who
        self._script = load_script()
        self.calls: list[list[str]] = []
        self.forwards: dict[int, int] = {}
        self.down = False
        self._servers: dict[int, ThreadingHTTPServer] = {}

    @property
    def requests(self) -> list[str]:
        return [call[-1] for call in self.calls if "-O" not in call]

    def __call__(self, argv, timeout_s) -> Done:
        self.calls.append(list(argv))
        if self.down:
            return Done(255, "", "ssh: connect to host farm port 22: Connection refused\n")
        if "-O" in argv:
            action = argv[argv.index("-O") + 1]
            _, local, _, host_port = (int(part) if part.isdigit() else part for part in argv[-3].split(":"))
            if action == "cancel":
                self.forwards.pop(local, None)
                if local in self._servers:
                    self._servers.pop(local).shutdown()
            else:
                self.forwards[local] = host_port
                if host_port in self._adb.forwards and local not in self._servers:
                    self._servers[local] = ThreadingHTTPServer(("127.0.0.1", local), DeviceServer)
                    threading.Thread(
                        target=self._servers[local].serve_forever, args=(0.01,), daemon=True
                    ).start()
            return Done(0, "", "")
        status, said = call_host(self._script, self._state, self._adb.port, self._who, argv[-1])
        return Done(status, said, "")

    def close(self) -> None:
        for server in self._servers.values():
            server.shutdown()


class TunnelAdb:
    def __init__(self, version: str = "1.0.41") -> None:
        self.version = version
        self.running = True
        self.ran: list[tuple[str, ...]] = []

    def run(self, args, timeout_s=15.0) -> AdbResult:
        self.ran.append(tuple(args))
        match tuple(args):
            case ("version",):
                return AdbResult(0, f"Android Debug Bridge version {self.version}\nVersion 37.0.1\n", "")
            case (*_, "shell", script) if script == lifetime.STATUS_SCRIPT:
                pid = 4242 if self.running else ""
                return AdbResult(0, f"server={pid}\nwatchdog={pid}\nlimit=900\nnow=1000\nlast=997\n", "")
            case (*_, "shell", script) if script == lifetime.STOP_SCRIPT:
                self.running = False
            case (*_, "shell", script) if script == lifetime.start_script(900):
                self.running = True
            case (*_, "shell", script) if "getprop" in script:
                return AdbResult(0, FACTS, "")
        return AdbResult(0, "", "")

    @property
    def sent(self) -> list[tuple[str, ...]]:
        address = ("-H", "127.0.0.1", "-P")
        return [args[len(address) + 1 :] for args in self.ran if args[: len(address)] == address]
