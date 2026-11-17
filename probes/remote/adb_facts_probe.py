#!/usr/bin/env python3
"""Measures the adb facts that the remote mode builds on. It prints one line per check.

    python3 -I probes/remote/adb_facts_probe.py client
    python3 -I probes/remote/adb_facts_probe.py forward emulator-5570
    python3 -I probes/remote/adb_facts_probe.py facts SERIAL [RUNS]
    python3 -I probes/remote/adb_facts_probe.py hang emulator-5554

`client` needs no device and no adb server. It runs the adb client on PATH (or `$ADB`) against
ports where nothing listens, and against a stand-in server that records what it is asked and
answers nothing else. Its one real server is a control that is started with USB, emulator and mDNS
discovery off, on a port of its own, and killed again.

`forward` speaks adb's socket protocol to the server on 127.0.0.1:5037 about one serial. Run it
against an emulator, never against a phone with accounts: it opens and closes port forwards and
sends nothing to the device. For an emulator it also runs `adb connect` to the emulator's own adb
port, so the server lists the one device under a second serial, and disconnects it again. That
stands in for a second phone.

`facts` sends one phone the shell line in `FACTS`, the one line `host/phone_manifest.py` sends, over
the same socket protocol, and times it. The line only reads, so this is the one check that may run
against a phone with accounts. It never runs the adb client, so it can run on a phone host, whose
adb server belongs to the service manager: `python3 -I - facts SERIAL < adb_facts_probe.py` there.
With no serial it prints what the server lists and asks no phone anything.

`hang` starts `sleep 60` on the device, closes the socket and looks for the process. It refuses a
serial that is not an emulator's.
"""

from __future__ import annotations

import os
import socket
import statistics
import subprocess
import sys
import threading
import time

ADB = os.environ.get("ADB", "adb")
SERVER = ("127.0.0.1", 5037)
DEVICE_PORT = 9008
QUIET = {"ADB_USB": "0", "ADB_EMU": "0", "ADB_MDNS": "0", "ADB_MDNS_OPENSCREEN": "0"}
FACTS = "getprop sys.boot_completed; getprop ro.build.version.release; dumpsys battery"
UNLISTED = "0a1b2c3d4e5f6a7b"


def check(name: str, expected: object, seen: object) -> None:
    verdict = "PASS" if expected == seen else "FAIL"
    print(f"{verdict}  {name}: {seen!r}" + ("" if expected == seen else f" (expected {expected!r})"))


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def listening(port: int, within_s: float = 3.0) -> bool:
    deadline = time.monotonic() + within_s
    while time.monotonic() < deadline:
        with socket.socket() as sock:
            sock.settimeout(0.2)
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.1)
    return False


def client(args: list[str], env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [ADB, *args],
        env={**os.environ, **QUIET, **(env or {})},
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        timeout=30,
    )


class StandIn:
    def __init__(self, version: int) -> None:
        self.version = version
        self.requests: list[str] = []
        self._sock = socket.create_server(("127.0.0.1", 0))
        self.port = self._sock.getsockname()[1]
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self) -> None:
        while True:
            connection, _ = self._sock.accept()
            with connection:
                try:
                    request = connection.recv(int(connection.recv(4), 16)).decode()
                except ValueError:
                    continue
                self.requests.append(request)
                if request == "host:version":
                    connection.sendall(b"OKAY0004%04x" % self.version)
                elif request == "host:kill":
                    connection.sendall(b"OKAY")
                else:
                    connection.sendall(b"OKAY0000")


def client_checks() -> None:
    print(client(["version"]).stdout.splitlines()[0])

    nothing = free_port()
    done = client(["-H", "127.0.0.1", "-P", str(nothing), "devices"])
    check("-H 127.0.0.1 -P <port> with nothing listening fails", 1, done.returncode)
    print(f"      stderr: {done.stderr.strip()[:160]}")
    check("-H 127.0.0.1 -P <port> starts no server on that port", False, listening(nothing))

    nothing = free_port()
    done = client(["devices"], {"ADB_SERVER_SOCKET": f"tcp:127.0.0.1:{nothing}"})
    check("ADB_SERVER_SOCKET=tcp:127.0.0.1:<port> with nothing listening fails", 1, done.returncode)
    print(f"      stderr: {done.stderr.strip()[:160]}")
    check("ADB_SERVER_SOCKET=tcp:127.0.0.1:<port> starts no server on that port", False, listening(nothing))

    control = free_port()
    done = client(["-P", str(control), "devices"])
    started = listening(control)
    check("control: -P <port> alone, which means localhost, starts a server there", True, started)
    print(f"      stderr: {' | '.join(done.stderr.strip().splitlines())[:160]}")
    if started:
        client(["-P", str(control), "kill-server"])
        check("control: that server is gone again", False, listening(control, 1.0))

    older = StandIn(40)
    done = client(["-H", "127.0.0.1", "-P", str(older.port), "devices"])
    time.sleep(0.5)
    killed = "host:kill" in older.requests
    check("a client that finds another protocol number asks that server to die", True, killed)
    print(f"      requests: {older.requests}")
    print(f"      stderr: {' | '.join(done.stderr.strip().splitlines())[:200]}")

    same = StandIn(41)
    done = client(["-H", "127.0.0.1", "-P", str(same.port), "devices"])
    check("a client that finds its own protocol number sends no kill", False, "host:kill" in same.requests)
    print(f"      requests: {same.requests}")

    silent = StandIn(41)
    done = client(["-H", "127.0.0.1", "-P", str(silent.port), "version"])
    check("`adb version` asks the server nothing", [], silent.requests)


def ask(request: str) -> bytes:
    with socket.create_connection(SERVER, 5) as sock:
        payload = request.encode()
        sock.sendall(b"%04x" % len(payload) + payload)
        sock.settimeout(2)
        answer = b""
        try:
            while chunk := sock.recv(4096):
                answer += chunk
        except TimeoutError:
            pass
        return answer


def forward_checks(serial: str) -> None:
    check("host:version is 4 hex digits of the protocol number", b"OKAY00040029", ask("host:version"))
    rows = ask("host:devices-l")
    print(f"      host:devices-l: {rows[8:].decode().strip()!r}")

    opened = ask(f"host-serial:{serial}:forward:tcp:0;tcp:{DEVICE_PORT}")
    check("forward tcp:0 answers OKAY OKAY and the port as a counted string", b"OKAYOKAY", opened[:8])
    port = int(opened[12:])
    check("the counted string is the port", opened, b"OKAYOKAY%04x%d" % (len(str(port)), port))
    check("the port listens on this computer", True, listening(port, 1.0))

    again = ask(f"host-serial:{serial}:forward:tcp:{port};tcp:{DEVICE_PORT}")
    check("asking again for that same port answers OKAY OKAY and no port", b"OKAYOKAY", again)
    listed = [row for row in ask("host:list-forward")[8:].decode().splitlines() if row.startswith(serial)]
    check("and leaves one forward for the serial", [f"{serial} tcp:{port} tcp:{DEVICE_PORT}"], listed)

    with socket.socket() as taken:
        taken.bind(("127.0.0.1", 0))
        busy = taken.getsockname()[1]
        refused = ask(f"host-serial:{serial}:forward:tcp:{busy};tcp:{DEVICE_PORT}")
        check("a port another process holds is FAIL", b"FAIL", refused[:4])
        print(f"      message: {refused[8:].decode()!r}")

    closed = ask(f"host-serial:{serial}:killforward:tcp:{port}")
    check("killforward answers OKAY OKAY", b"OKAYOKAY", closed)
    check("the port listens no more", False, listening(port, 0.5))
    twice = ask(f"host-serial:{serial}:killforward:tcp:{port}")
    check("killforward of a port that is closed is FAIL", b"FAIL", twice[:4])
    print(f"      message: {twice[8:].decode()!r}")

    missing = ask(f"host-serial:{UNLISTED}:forward:tcp:0;tcp:{DEVICE_PORT}")
    check("forward for a serial adb does not list is FAIL", b"FAIL", missing[:4])
    print(f"      raw: {missing!r}")


def forwards() -> list[str]:
    return ask("host:list-forward")[8:].decode().splitlines()


def rebind_checks(serial: str) -> None:
    port = int(ask(f"host-serial:{serial}:forward:tcp:0;tcp:{DEVICE_PORT}")[12:])
    mine = f"{serial} tcp:{port} tcp:{DEVICE_PORT}"
    held = ask(f"host-serial:{serial}:forward:norebind:tcp:{port};tcp:{DEVICE_PORT}")
    check("norebind for a port adb holds is FAIL, even for the same phone and target", b"FAIL", held[:4])
    print(f"      message: {held[8:].decode()!r}")
    check("and the forward is as it was", [mine], forwards())

    moved = ask(f"host-serial:{serial}:forward:tcp:{port};tcp:{DEVICE_PORT + 1}")
    check("a plain forward for a held port answers OKAY OKAY and no port", b"OKAYOKAY", moved)
    check("and moves the port to the new target", [f"{serial} tcp:{port} tcp:{DEVICE_PORT + 1}"], forwards())

    ask(f"host-serial:{serial}:killforward:tcp:{port}")
    back = ask(f"host-serial:{serial}:forward:norebind:tcp:{port};tcp:{DEVICE_PORT}")
    check(
        "norebind for a free port makes the forward and answers the port",
        b"OKAYOKAY%04x%d" % (len(str(port)), port),
        back,
    )
    check("and adb lists it", [mine], forwards())

    with socket.socket() as taken:
        taken.bind(("127.0.0.1", 0))
        refused = ask(f"host-serial:{serial}:forward:norebind:tcp:{taken.getsockname()[1]};tcp:{DEVICE_PORT}")
        check("norebind for a port another process holds is FAIL", b"FAIL", refused[:4])
        print(f"      message: {refused[8:].decode()!r}")

    if not serial.startswith("emulator-"):
        ask(f"host-serial:{serial}:killforward:tcp:{port}")
        return
    twin = f"127.0.0.1:{int(serial.removeprefix('emulator-')) + 1}"
    print(f"      adb connect {twin}: {client(['connect', twin]).stdout.strip()}")
    try:
        stolen = ask(f"host-serial:{twin}:forward:tcp:{port};tcp:{DEVICE_PORT}")
        check("a plain forward for a port that another serial holds is OKAY OKAY", b"OKAYOKAY", stolen)
        check("and the port now belongs to that serial", [f"{twin} tcp:{port} tcp:{DEVICE_PORT}"], forwards())
        kept = ask(f"host-serial:{serial}:forward:norebind:tcp:{port};tcp:{DEVICE_PORT}")
        check("norebind for a port that another serial holds is FAIL", b"FAIL", kept[:4])
        closed = ask(f"host-serial:{serial}:killforward:tcp:{port}")
        check("killforward closes a port whatever serial it names", (b"OKAYOKAY", []), (closed, forwards()))
    finally:
        client(["disconnect", twin])


def named_port_checks(serial: str, tries: int = 20) -> None:
    opened = 0
    for _ in range(tries):
        port = free_port()
        answer = ask(f"host-serial:{serial}:forward:norebind:tcp:{port};tcp:{DEVICE_PORT}")
        opened += answer == b"OKAYOKAY%04x%d" % (len(str(port)), port)
        ask(f"host-serial:{serial}:killforward:tcp:{port}")
    check(
        f"norebind opens a number that the kernel just called free, in each of {tries} tries", tries, opened
    )
    check("and no forward is left", [], forwards())


def open_shell(serial: str, command: str) -> tuple[socket.socket, list[bytes], list[float]]:
    stamps = [time.monotonic()]
    sock = socket.create_connection(SERVER, 5)
    sock.settimeout(20)
    answers = []
    for request in (f"host:transport:{serial}", f"shell:{command}"):
        payload = request.encode()
        sock.sendall(b"%04x" % len(payload) + payload)
        answers.append(sock.recv(4, socket.MSG_WAITALL))
        stamps.append(time.monotonic())
        if answers[-1] != b"OKAY":
            break
    return sock, answers, stamps


def shell(serial: str, command: str) -> tuple[list[bytes], bytes, list[int]]:
    sock, answers, stamps = open_shell(serial, command)
    output = b""
    with sock:
        while chunk := sock.recv(4096):
            if not output:
                stamps.append(time.monotonic())
            output += chunk
    stamps.append(time.monotonic())
    return answers, output, [round((stamp - stamps[0]) * 1000) for stamp in stamps[1:]]


def facts_checks(serial: str, runs: int) -> None:
    check("host:version is 4 hex digits of the protocol number", b"OKAY00040029", ask("host:version"))
    answers, output, _ = shell(serial, FACTS)
    check("host:transport:<serial> and shell:<FACTS> each answer the 4 bytes OKAY", [b"OKAY"] * 2, answers)
    print(f"      what follows, to the close: {output!r}")
    check("no line of it ends with a carriage return", False, b"\r" in output)
    lines = output.decode().splitlines()
    check("line 1 is sys.boot_completed", "1", lines[0])
    print(f"      line 2, ro.build.version.release: {lines[1]!r}")
    check("line 3 opens dumpsys battery", "Current Battery Service state:", lines[2])
    battery = {key.strip(): value.strip() for key, _, value in (line.partition(":") for line in lines[3:])}
    print(f"      level: {battery.get('level')!r}, temperature: {battery.get('temperature')!r}")

    totals = []
    for _ in range(runs):
        marks = shell(serial, FACTS)[2]
        totals.append(marks[-1])
        print(f"      ms from the connect to each OKAY, to the first byte and to the close: {marks}")
    if totals:
        print(
            f"      {runs} runs, connect to close: median {statistics.median(totals)} ms,"
            f" least {min(totals)} ms, most {max(totals)} ms"
        )

    answers, said, _ = shell(UNLISTED, FACTS)
    check("a serial adb does not list is FAIL at the transport request", [b"FAIL"], answers)
    print(f"      raw: {said!r}")


def hang_checks(serial: str) -> None:
    if not serial.startswith("emulator-"):
        sys.exit("`hang` starts a process on the device. Run it against an emulator, never against a phone.")

    def sleeping() -> list[bytes]:
        return shell(serial, "pidof sleep")[1].split()

    check("control: no sleep runs on the device", [], sleeping())
    sock, answers, _ = open_shell(serial, "sleep 60")
    check("shell:sleep 60 answers OKAY", [b"OKAY"] * 2, answers)
    sock.settimeout(1.0)
    try:
        silent = sock.recv(4096)
    except TimeoutError:
        silent = None
    check("and then sends nothing and does not close", None, silent)
    check("the sleep runs on the device while the socket is open", 1, len(sleeping()))
    sock.close()
    closed = time.monotonic()
    while sleeping() and time.monotonic() - closed < 10:
        time.sleep(0.1)
    check("closing the socket ends the sleep on the device", [], sleeping())
    print(f"      it was gone {time.monotonic() - closed:.1f} s after the close, or sooner")


if __name__ == "__main__":
    match sys.argv[1:]:
        case ["client"]:
            client_checks()
        case ["forward", serial]:
            forward_checks(serial)
            rebind_checks(serial)
            named_port_checks(serial)
        case ["facts"]:
            print(f"host:devices-l: {ask('host:devices-l')[8:].decode()!r}")
        case ["facts", serial, *runs]:
            facts_checks(serial, int(runs[0]) if runs else 10)
        case ["hang", serial]:
            hang_checks(serial)
        case _:
            sys.exit(__doc__)
