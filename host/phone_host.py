#!/usr/bin/python3 -IS
"""phone-host: which phone on this computer is free, and who holds the others.

It runs on the computer the phones are plugged into, as the forced command of every ssh key that
may use them. It needs the standard library and a running adb server, and nothing else. Each call
reads or changes one small file and ends, so no process stays behind.

    ssh HOST                              a table, for people
    ssh HOST list [--holder ID]           the same facts as JSON
    ssh HOST lease SERIAL --holder ID [--task TEXT] [--ttl SECONDS] [--port DEVICE_PORT]
    ssh HOST release SERIAL --holder ID
    phone-host key NAME                   on the host, by its admin: the authorized_keys options for NAME

Who asks comes from the key and never from the caller. sshd runs `phone-host --who NAME`, and what
the caller typed arrives in SSH_ORIGINAL_COMMAND. This script splits it into words and never hands
it to a shell.

A lease says that holder ID of person NAME drives SERIAL for TASK until a deadline. The holder
moves the deadline by asking again. A holder that stops asking loses the phone at the deadline, so
a crash or a dropped network frees the phone with no cleanup. `--port` also asks for one port on
this host's loopback that reaches DEVICE_PORT on the phone. The port belongs to the lease: a
release closes it, and so does another holder who takes the phone after the deadline.

Every answer is one JSON object on one line. Exit status 0 is a yes, 1 is "another holder has it",
2 is a request this script could not serve. `host/README.md` of agent-phone shows each answer.

`id` names one unbroken tenure. It stays the same while one holder renews, and also when that
holder comes back after its deadline and nobody else took the phone in between. It changes when
the phone passes to another holder. A client that sees a new id knows another computer may have
driven the phone since its last call.

The adb server is asked over its own socket protocol, never through the `adb` binary, which
starts a server when it finds none. This host's server belongs to its service manager. Its port is
5037, or `ANDROID_ADB_SERVER_PORT` as for adb itself. The leases live in `$XDG_STATE_HOME/phone-host`,
by default `~/.local/state/phone-host`.
"""

from __future__ import annotations

import argparse
import collections
import fcntl
import json
import os
import shlex
import socket
import stat
import sys
import time

WIRE_VERSION = 1
YES, BUSY, UNSERVED = 0, 1, 2
ADB_TIMEOUT_S = 3.0
TTL_S = 120
TTL_RANGE_S = (10, 3600)
PORT_TRIES = 8
TASK_CHARS = 80
WORD_CHARS = 64
SERIAL_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-")
NAME_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789_-")
RECORD_KEYS = frozenset({"who", "holder", "task", "id", "boot", "since", "until", "port", "device_port"})
BOOT_ID = "/proc/sys/kernel/random/boot_id"
KEY_OPTIONS = (
    'command="{script} --who {name}",restrict,port-forwarding,'
    'permitopen="127.0.0.1:*",permitlisten="127.0.0.1:1"'
)
"""`restrict` takes away the pty, agent and X11 forwarding and every port forward.
`port-forwarding` gives forwards back, `permitopen` limits `-L` to TCP ports of this host's
loopback, and `permitlisten` names a port no user can bind, so `-R` opens no TCP port. No option
stops `-R` to a Unix socket path (probes/remote/FINDINGS.md, R1-1 to R1-10, R1-15 to R1-18)."""


class Refused(Exception):
    def __init__(self, error: str, message: str, status: int = UNSERVED) -> None:
        super().__init__(message)
        self.status = status
        self.body = {"v": WIRE_VERSION, "ok": False, "error": error, "message": message}


Reply = collections.namedtuple("Reply", "status body record port_to_close")


def decide(request: argparse.Namespace, who: str, record: dict | None, ready: bool, now: float) -> Reply:
    """The whole lease policy for one phone, with no clock, file or socket in it.

        the record            the asker        the answer
        none                  anyone           grant: a new id, since = now
        the asker's, in time  its holder       renew: the same id and port, a later deadline
        the asker's, late     its holder       renew: nobody held the phone in between
        another's, in time    anyone else      busy, exit 1, nothing changes
        another's, late       anyone else      take over: close the old port, grant with a new id

    A release by the holder removes the record and closes its port. A release by anyone else is a
    yes that changes nothing, so it can run twice and can never free another holder's phone.
    """
    mine = record is not None and (record["who"], record["holder"]) == (who, request.holder)
    if request.verb == "release":
        yes = {"v": WIRE_VERSION, "ok": True}
        return Reply(YES, yes, None, record["port"]) if mine else Reply(YES, yes, record, None)
    if not ready:
        raise Refused("no_device", f"adb lists no ready device {request.serial}.")
    if record is not None and not mine and record["until"] > now:
        facts = lease_facts(record, who, request.holder, now)
        return Reply(BUSY, {"v": WIRE_VERSION, "ok": False, "error": "busy", "lease": facts}, record, None)
    keeps_port = mine and request.port is not None and record["device_port"] == request.port
    granted = {
        "who": who,
        "holder": request.holder,
        "task": request.task,
        "id": record["id"] if mine else request.fresh,
        "since": record["since"] if mine else now,
        "until": now + request.ttl,
        "port": record["port"] if keeps_port else None,
        "device_port": request.port,
    }
    facts = lease_facts(granted, who, request.holder, now)
    body = {"v": WIRE_VERSION, "ok": True, "id": granted["id"], "port": granted["port"], "lease": facts}
    return Reply(YES, body, granted, None if record is None or keeps_port else record["port"])


def lease_facts(record: dict, who: str, holder: str | None, now: float) -> dict[str, object]:
    """What a caller may know of a lease. Never the holder id, which is what proves a renewal."""
    return {
        "by": record["who"],
        "task": record["task"],
        "held_s": int(now - record["since"]),
        "free_in_s": max(0, round(record["until"] - now)),
        "mine": (record["who"], record["holder"]) == (who, holder),
    }


def listing(
    who: str, holder: str | None, records: dict[str, dict], phones: list[dict], version: int, now: float
) -> dict:
    rows = []
    for phone in phones:
        record = records.get(phone["serial"])
        live = record is not None and record["until"] > now
        rows.append({**phone, "lease": lease_facts(record, who, holder, now) if live else None})
    return {"v": WIRE_VERSION, "adb": version, "phones": rows}


def table(answer: dict) -> str:
    rows = []
    for phone in answer["phones"]:
        lease = phone["lease"]
        if lease is None:
            state, who = "free" if phone["state"] == "device" else phone["state"], ""
        else:
            held = f"{lease['held_s'] // 60} min" if lease["held_s"] >= 60 else f"{lease['held_s']} s"
            task = lease["task"] or "no task named"
            state, who = "busy", f"{lease['by']}: {task} ({held}, free in {lease['free_in_s']} s)"
        rows.append((phone["serial"], phone["model"], state, who))
    if not rows:
        return "adb lists no phone.\n"
    widths = [max(len(row[column]) for row in rows) for column in range(2)]
    return "".join(
        f"{serial.ljust(widths[0])}  {model.ljust(widths[1])}  {state}  {who}".rstrip() + "\n"
        for serial, model, state, who in rows
    )


def adb(request: str, port: int) -> bytes:
    """One request to the adb server, and what it sends after its first OKAY. The server closes
    the connection after each answer, which is how the end is found."""
    payload = request.encode()
    try:
        with socket.create_connection(("127.0.0.1", port), ADB_TIMEOUT_S) as sock:
            sock.sendall(b"%04x" % len(payload) + payload)
            answer = b""
            while chunk := sock.recv(4096):
                answer += chunk
    except OSError as error:
        raise Refused("adb_down", f"The adb server on this host does not answer: {error}.") from None
    if answer[:4] != b"OKAY":
        raise Refused("adb", answer[8:].decode(errors="replace") or f"adb refused {request!r}.")
    return answer[4:]


def phones(port: int) -> list[dict[str, str]]:
    rows = []
    for line in adb("host:devices-l", port)[4:].decode(errors="replace").splitlines():
        fields = line.split()
        if len(fields) >= 2:
            model = next((field[6:] for field in fields[2:] if field.startswith("model:")), "")
            rows.append({"serial": fields[0], "model": model, "state": fields[1]})
    return rows


def forwards(port: int) -> list[str]:
    """One `SERIAL tcp:HOST_PORT tcp:DEVICE_PORT` per forward. A record's port is its phone's only
    while adb lists it so: a server that started again gives the number to another phone (R2-13)."""
    return adb("host:list-forward", port)[4:].decode(errors="replace").splitlines()


def free_port() -> int:
    """A port of 127.0.0.1 that is free at this moment. The kernel picks it, so this account may bind it."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def open_port(serial: str, host_port: int, device_port: int, taken: set, port: int) -> int:
    """Make a port of 127.0.0.1 reach `device_port` on the phone, and return it. `host_port` is
    the port the lease had, or 0. It stays while adb lists it for this phone. When adb forgot it,
    the same number is asked for first, then numbers that are free. Each is asked for with
    `norebind`, which adb refuses when another phone or process has it (R2-12, R2-14, R2-15). adb
    never picks, because it would open a number in `taken`, where another holder may still point."""
    if host_port and f"{serial} tcp:{host_port} tcp:{device_port}" in forwards(port):
        return host_port
    said = "every free port is in the record of another lease"
    for attempt in range(PORT_TRIES):
        candidate = host_port if host_port and not attempt else free_port()
        if candidate != host_port and candidate in taken:
            continue
        try:
            adb(f"host-serial:{serial}:forward:norebind:tcp:{candidate};tcp:{device_port}", port)
            return candidate
        except Refused as refused:
            if refused.body["error"] == "adb_down":
                raise
            said = str(refused)
    raise Refused("host", f"adb opened no port for {serial} in {PORT_TRIES} tries: {said}")


def close_port(serial: str, host_port: int, port: int) -> None:
    """Only a port that adb lists for this phone, because `killforward` closes a port whatever
    phone it belongs to (R2-16). A port that is already closed is fine, and so is an adb server
    that is down: its forwards went with it (R2-10)."""
    try:
        if any(row.startswith(f"{serial} tcp:{host_port} ") for row in forwards(port)):
            adb(f"host-serial:{serial}:killforward:tcp:{host_port}", port)
    except Refused:
        pass


def boot_time() -> float:
    """Linux counts a suspended host in CLOCK_BOOTTIME, so a lease cannot outlive its deadline."""
    return time.clock_gettime(time.CLOCK_BOOTTIME)


def boot_id(path: str = BOOT_ID) -> str:
    """A record from another boot is void, because its deadline was read from a clock that
    started again. A host that cannot tell one boot from the next would keep such a record, so it
    serves nothing."""
    with open(path) as file:
        if found := file.read().strip():
            return found
    raise OSError(f"{path} holds no boot id")


def read_record(state: str, serial: str, boot: str) -> dict | None:
    """A record past `until` is still returned: its owner may come back for it, and its port must
    be closed by whoever takes the phone next. A socket or a link at the record's path is what a
    key left there (R1-15). It is no record and is never opened. Any other fault of the file
    reaches `main`, because a phone whose record cannot be read must not look free."""
    path = os.path.join(state, f"{serial}.json")
    try:
        if not stat.S_ISREG(os.lstat(path).st_mode):
            return None
        with open(os.open(path, os.O_RDONLY | os.O_NOFOLLOW)) as file:
            record = json.load(file)
    except (FileNotFoundError, ValueError):
        return None
    if not isinstance(record, dict) or record.keys() != RECORD_KEYS or record["boot"] != boot:
        return None
    return record


def write_record(state: str, serial: str, record: dict | None) -> None:
    """A reader without the lock sees the old record or the new one, never a half. The new one is
    written to a file that this call makes, whatever a key left under that name."""
    path = os.path.join(state, f"{serial}.json")
    fresh = f"{path}.tmp"
    unwanted = path if record is None else fresh
    if os.path.lexists(unwanted):
        os.unlink(unwanted)
    if record is not None:
        with open(os.open(fresh, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as file:
            json.dump(record, file)
        os.replace(fresh, path)


def change(request: argparse.Namespace, who: str, state: str, adb_port: int, boot: str, clock) -> Reply:
    """One `flock` covers every phone. It is on the state folder and not on a file in it, because
    a key can put a socket at a path that is free and not at one that exists (R1-15, R1-16)."""
    folder = os.open(state, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        fcntl.flock(folder, fcntl.LOCK_EX)
        before = read_record(state, request.serial, boot)
        ready = request.verb == "lease" and any(
            phone["serial"] == request.serial and phone["state"] == "device" for phone in phones(adb_port)
        )
        reply = decide(request, who, before, ready, clock())
        if reply.port_to_close is not None:
            close_port(request.serial, reply.port_to_close, adb_port)
        after = reply.record
        if after is not before:
            if after is not None and after["device_port"] is not None:
                # The computer of every holder on record may still point at its port, late or not.
                held = (name[:-5] for name in os.listdir(state) if name.endswith(".json"))
                taken = {found["port"] for serial in held if (found := read_record(state, serial, boot))}
                reply.body["port"] = after["port"] = open_port(
                    request.serial, after["port"] or 0, after["device_port"], taken, adb_port
                )
            write_record(state, request.serial, after and {**after, "boot": boot})
    finally:
        os.close(folder)
    return reply


def answer_list(who: str, holder: str | None, state: str, adb_port: int, boot: str, now: float) -> dict:
    """Reads the records without the lock, because every write is a rename."""
    rows = phones(adb_port)
    records = {row["serial"]: record for row in rows if (record := read_record(state, row["serial"], boot))}
    version = int(adb("host:version", adb_port)[4:], 16)
    return listing(who, holder, records, rows, version, now)


class Words(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise Refused("usage", message)


def word(text: str) -> str:
    if not 0 < len(text) <= WORD_CHARS or not set(text) <= SERIAL_CHARS:
        raise argparse.ArgumentTypeError(f"{text!r} is not 1 to {WORD_CHARS} letters, digits or . _ : -")
    return text


def whole(least: int, most: int):
    def parse(text: str) -> int:
        if not text.isdigit() or not least <= int(text) <= most:
            raise argparse.ArgumentTypeError(f"{text!r} is not a whole number from {least} to {most}")
        return int(text)

    return parse


def parse_request(words: list[str]) -> argparse.Namespace:
    """The serial becomes a file name and the task is shown to other people, so the serial is held
    to adb's characters and the task loses what does not print."""
    parser = Words(prog="phone-host", add_help=False)
    verbs = parser.add_subparsers(dest="verb", required=True, parser_class=Words)
    verbs.add_parser("list", add_help=False).add_argument("--holder", type=word)
    lease = verbs.add_parser("lease", add_help=False)
    lease.add_argument("--task", default="")
    lease.add_argument("--ttl", type=whole(*TTL_RANGE_S), default=TTL_S)
    lease.add_argument("--port", type=whole(1, 65535))
    for verb in (lease, verbs.add_parser("release", add_help=False)):
        verb.add_argument("serial", type=word)
        verb.add_argument("--holder", type=word, required=True)
    request = parser.parse_args(words)
    if request.verb == "lease":
        request.task = "".join(char for char in request.task if char.isprintable())[:TASK_CHARS]
        request.fresh = os.urandom(4).hex()
    return request


def main(argv: list[str], env: dict[str, str], clock=boot_time, boot=boot_id) -> int:
    """`--who NAME` comes from the forced command, which has no other word. So words after it
    are an admin's, typed in a shell on the host, and without them the request is what sshd put in
    SSH_ORIGINAL_COMMAND. Without `--who` the only verb is `key`. A test passes its own `clock`
    and `boot`, so this file has no second way to read either."""
    try:
        match argv:
            case ["key", name] if set(name) <= NAME_CHARS and name:
                sys.stdout.write(KEY_OPTIONS.format(script=os.path.realpath(__file__), name=name) + "\n")
                return YES
            case ["--who", who, *words] if set(who) <= NAME_CHARS and who:
                pass
            case _:
                raise Refused("usage", "phone-host --who NAME [REQUEST], or phone-host key NAME")
        request = parse_request(words or shlex.split(env.get("SSH_ORIGINAL_COMMAND", "")) or ["list"])
        base = env.get("XDG_STATE_HOME") or os.path.join(os.path.expanduser("~"), ".local", "state")
        state = os.path.join(base, "phone-host")
        os.makedirs(state, mode=0o700, exist_ok=True)
        adb_port = int(env.get("ANDROID_ADB_SERVER_PORT") or 5037)
        this_boot = boot()
        if request.verb == "list":
            answer = answer_list(who, request.holder, state, adb_port, this_boot, clock())
            asked_for_json = bool(words or env.get("SSH_ORIGINAL_COMMAND", "").strip())
            sys.stdout.write(
                json.dumps(answer, separators=(",", ":")) + "\n" if asked_for_json else table(answer)
            )
            return YES
        reply = change(request, who, state, adb_port, this_boot, clock)
    except ValueError as error:
        reply = Refused("usage", str(error))
    except Refused as refused:
        reply = refused
    except OSError as error:
        reply = Refused("host", f"This host cannot serve the request: {error}.")
    sys.stdout.write(json.dumps(reply.body, separators=(",", ":")) + "\n")
    return reply.status


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:], dict(os.environ)))
