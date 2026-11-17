#!/usr/bin/python3 -IS
"""phone-manifest: the phones plugged into this computer, and whether each one is healthy.

    phone-manifest [--host 127.0.0.1] [--port 8037] [--every 30]
    curl http://127.0.0.1:8037/phones       the manifest, as JSON
    curl -f http://127.0.0.1:8037/health    fails unless adb answers and every phone is healthy

The main thread asks adb about every phone, sleeps `--every` seconds and asks again. A second
thread answers HTTP with the result of the last round, so a request never waits for adb or for a
phone. A round that fails in a way this file did not foresee ends the process, and the service
manager starts it again. So no manifest comes from a loop that died.

It only reads. It sends adb `host:devices-l` and, to a phone in state `device`, the shell line in
`FACTS`. It speaks the adb server's own socket protocol and never runs the `adb` binary, which
starts a server when it finds none. In agent-phone, `host/phone-manifest.md` shows each answer,
and an id such as R2-18 names a measurement in `probes/remote/FINDINGS.md`.
"""

import argparse
import dataclasses
import enum
import json
import os
import re
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

FACTS = "getprop sys.boot_completed; getprop ro.build.version.release; dumpsys battery"
DEADLINE_S = 3.0  # A Galaxy J7 answers FACTS in 0.06 to 0.11 s (R2-22).
BATTERY_LOW = 15  # Android's own low-battery level.
HOT_C = 45.0  # A lithium cell should stop charging there.


class Problem(enum.StrEnum):
    GONE = "gone"
    UNAUTHORIZED = "unauthorized"
    NOT_READY = "not_ready"
    NO_ANSWER = "no_answer"
    BOOTING = "booting"
    HOT = "hot"
    BATTERY_LOW = "battery_low"


@dataclasses.dataclass(frozen=True)
class Facts:
    booted: bool
    android: str
    battery: int | None
    temp_c: float | None


def diagnose(state: str | None, facts: Facts | None) -> Problem | None:
    if state is None:
        return Problem.GONE
    if state == "unauthorized":
        return Problem.UNAUTHORIZED
    if state != "device":
        return Problem.NOT_READY
    if facts is None:
        return Problem.NO_ANSWER
    if not facts.booted:
        return Problem.BOOTING
    if facts.temp_c is not None and facts.temp_c > HOT_C:
        return Problem.HOT
    if facts.battery is not None and facts.battery < BATTERY_LOW:
        return Problem.BATTERY_LOW
    return None


@dataclasses.dataclass(frozen=True)
class Phone:
    serial: str
    state: str | None
    model: str
    android: str
    facts: Facts | None
    seen: str

    @property
    def problem(self) -> Problem | None:
        return diagnose(self.state, self.facts)


@dataclasses.dataclass(frozen=True)
class Manifest:
    adb_up: bool
    checked: str
    phones: tuple[Phone, ...]


def parse_devices(text: str) -> list[tuple[str, str, str]]:
    """adb names no model for a phone it cannot talk to. A state is one word, but for
    `no permissions` adb prints a sentence:

      0a1b2c3d4e5f6a7b       device usb:1-1.4 product:j7y17ltexx model:SM_J730F device:j7y17lte transport_id:1
      0a1b2c3d4e5f6a7b       no permissions (missing udev rules? user is in the plugdev group); see [...]
    """
    rows = []
    for line in text.splitlines():
        serial, _, rest = line.partition(" ")
        fields = rest.split()
        if fields:
            state = "no permissions" if rest.lstrip().startswith("no permissions") else fields[0]
            model = next((field[6:] for field in fields if field.startswith("model:")), "")
            rows.append((serial, state, model))
    return rows


def parse_facts(text: str) -> Facts:
    """Each maker adds lines of its own to `dumpsys battery` (R2-19), so only two keys are read:
    `level`, in percent, and `temperature`, in tenths of a degree Celsius."""
    boot, android = (text.splitlines() + ["", ""])[:2]
    level = re.search(r"^ *level: *(\d+)", text, re.MULTILINE)
    tenths = re.search(r"^ *temperature: *(-?\d+)", text, re.MULTILINE)
    return Facts(
        booted=boot.strip() == "1",
        android=android.strip(),
        battery=int(level[1]) if level else None,
        temp_c=int(tenths[1]) / 10 if tenths else None,
    )


def merge(before: tuple[Phone, ...], fresh: list[Phone]) -> tuple[Phone, ...]:
    """adb names no model and no Android release for an unauthorized phone, so its row keeps the
    ones of the round before."""
    rows = {phone.serial: dataclasses.replace(phone, state=None, facts=None) for phone in before}
    for phone in fresh:
        last = rows.get(phone.serial, phone)
        rows[phone.serial] = dataclasses.replace(
            phone, model=phone.model or last.model, android=phone.android or last.android
        )
    return tuple(rows[serial] for serial in sorted(rows))


def adb(port: int, *requests: str) -> str:
    """A shell's output has no length, so the server's answer is read to the close (R2-18).
    TimeoutError is an OSError. Closing the socket also ends a shell that hangs on the phone (R2-21)."""
    deadline = time.monotonic() + DEADLINE_S
    with socket.create_connection(("127.0.0.1", port), DEADLINE_S) as sock:

        def read(size: int) -> bytes:
            # A plain socket timeout starts again at every chunk, so a phone that trickles its
            # answer could hold a round for ever.
            left = deadline - time.monotonic()
            if left <= 0:
                raise TimeoutError
            sock.settimeout(left)
            return sock.recv(size)

        for request in requests:
            payload = request.encode()
            sock.sendall(b"%04x" % len(payload) + payload)
            if read(4) != b"OKAY":
                raise OSError(f"adb refused {request}")
        answer = b""
        while chunk := read(4096):
            answer += chunk
    return answer.decode(errors="replace")


def check(before: tuple[Phone, ...], adb_port: int, now: str) -> Manifest:
    try:
        listed = parse_devices(adb(adb_port, "host:devices-l")[4:])
    except OSError:
        return Manifest(adb_up=False, checked=now, phones=before)
    fresh = []
    for serial, state, model in listed:
        facts = None
        if state == "device":
            try:
                facts = parse_facts(adb(adb_port, f"host:transport:{serial}", f"shell:{FACTS}"))
            except OSError:
                pass
        fresh.append(Phone(serial, state, model, facts.android if facts else "", facts, seen=now))
    return Manifest(adb_up=True, checked=now, phones=merge(before, fresh))


def respond(path: str, manifest: Manifest) -> tuple[int, dict[str, object]]:
    if path == "/health":
        ok = manifest.adb_up and all(phone.problem is None for phone in manifest.phones)
        return (200, {"status": "ok"}) if ok else (503, {"status": "degraded"})
    if path != "/phones":
        return 404, {"error": {"type": "not_found", "message": "Try /phones or /health."}}
    if not manifest.adb_up:
        return 503, {"error": {"type": "adb_down", "message": "The adb server does not answer."}}
    rows = [
        {
            "serial": phone.serial,
            "model": phone.model,
            "android": phone.android,
            "state": phone.state,
            "healthy": phone.problem is None,
            "problem": phone.problem,
            "battery": phone.facts.battery if phone.facts else None,
            "tempC": phone.facts.temp_c if phone.facts else None,
            "seenAt": phone.seen,
        }
        for phone in manifest.phones
    ]
    return 200, {"checkedAt": manifest.checked, "phones": rows}


class Handler(BaseHTTPRequestHandler):
    timeout = 5

    def do_GET(self) -> None:
        status, body = respond(self.path, self.server.manifest)
        payload = json.dumps(body, indent=2).encode() + b"\n"
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: object) -> None:
        """Silent. The journal holds what changed, not one line per request."""


def log(event: str, **data: object) -> None:
    print(json.dumps({"event": event, **data}), file=sys.stderr, flush=True)


def advance(server: ThreadingHTTPServer, adb_port: int) -> None:
    last = server.manifest
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    server.manifest = check(last.phones, adb_port, now)
    if server.manifest.adb_up != last.adb_up:
        log("adb.up" if server.manifest.adb_up else "adb.down")
    known = {(phone.serial, phone.problem) for phone in last.phones}
    for phone in server.manifest.phones:
        if (phone.serial, phone.problem) not in known:
            log("phone.changed", serial=phone.serial, problem=phone.problem)


def main(argv: list[str], env: dict[str, str]) -> None:
    parser = argparse.ArgumentParser(
        prog="phone-manifest", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--host", default="127.0.0.1", help="the address to listen on (%(default)s)")
    parser.add_argument(
        "--port", type=int, default=8037, help="the TCP port, or 0 for a free one (%(default)s)"
    )
    parser.add_argument("--every", type=float, default=30, help="seconds between two rounds (%(default)s)")
    args = parser.parse_args(argv)
    if not 0 <= args.port <= 65535 or not 0 < args.every < float("inf"):
        parser.error("--port is a number from 0 to 65535, and --every is a number of seconds above 0")
    adb_port = int(env.get("ANDROID_ADB_SERVER_PORT") or 5037)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.manifest = Manifest(adb_up=True, checked="", phones=())
    log("manifest.start", host=args.host, port=server.server_port)
    advance(server, adb_port)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    while True:
        time.sleep(args.every)
        advance(server, adb_port)


if __name__ == "__main__":
    main(sys.argv[1:], dict(os.environ))
