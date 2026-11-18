"""Commands over the Mac's loopback ADB server. One command, one selected serial."""

import argparse
import fcntl
import math
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from uuid import uuid4

from redis.exceptions import RedisError
from store import Store

import adbutils
import uiautomator2 as u2
from uiautomator2._selector import Selector
from uiautomator2.core import DEFAULT_SERVER_PORT, _jsonrpc_call


def elements(device, selector):
    rows = []
    label = None
    if selector and "text" in selector:
        # Android's hierarchy dump represents each UTF-16 surrogate as a dot.
        label = re.sub(r"[\U00010000-\U0010FFFF]", "..", selector["text"].strip())
    for node in ET.fromstring(device.dump_hierarchy()).iter("node"):
        a = node.attrib
        bounds = list(map(int, re.findall(r"-?\d+", a.get("bounds", ""))))
        if len(bounds) != 4 or bounds[0] >= bounds[2] or bounds[1] >= bounds[3]:
            continue
        text, desc, full_id = a.get("text", ""), a.get("content-desc", ""), a.get("resource-id", "")
        short_id = full_id.split("/")[-1]
        if label is not None and text.strip() != label:
            continue
        if selector and "id" in selector and selector["id"] not in (full_id, short_id):
            continue
        rows.append(
            dict(
                text=text,
                desc=desc,
                id=short_id,
                full_id=full_id,
                center=[(bounds[0] + bounds[2]) // 2, (bounds[1] + bounds[3]) // 2],
                bounds=bounds,
                klass=a.get("class", ""),
                clickable=a.get("clickable") == "true",
                focused=a.get("focused") == "true",
            )
        )
    return rows


def public(row):
    return {k: row[k] for k in ("text", "desc", "id", "center", "clickable", "focused")}


class MatchError(ValueError):
    def __init__(self, count):
        super().__init__("ambiguous" if count else "not_found")
        self.matches = count


def one(rows):
    if len(rows) != 1:
        raise MatchError(len(rows))
    return rows[0]


def drive(adb, args, before_input):
    command, words = args.command, args.words
    on = json.loads(args.on) if args.on else None
    if command in ("open", "key", "swipe") or (command == "tap" and on is None):
        if command == "open":
            if not re.fullmatch(r"[A-Za-z]\w*(\.\w+)+", words[0]):
                raise ValueError("invalid_package")
            shell = ["monkey", "-p", words[0], "-c", "android.intent.category.LAUNCHER", "1"]
        else:
            kind = "keyevent" if command == "key" else command
            shell = ["input", kind, *(w.upper() if command == "key" else w for w in words)]
            if command == "swipe":
                shell.append("300")
            if command == "key" and not re.fullmatch(r"[A-Z0-9_]+", shell[-1]):
                raise ValueError("invalid_key")
        before_input()
        reply = adb.shell2(shell, timeout=15)
        if reply.returncode or (command == "open" and "Events injected: 1" not in reply.output):
            raise ValueError("Android refused " + command)
        return None

    if command == "screenshot":
        path = Path(words[0])
        image = adb.screenshot(error_ok=False)
        image.convert("RGB").save(path, format="JPEG", quality=90)
        return {"path": str(path.resolve()), "bytes": path.stat().st_size}

    device = u2.Device(adb)
    try:
        return drive_ui(device, adb, args, on, before_input)
    finally:
        # Hold the serial lock until our helper exits. Another CLI process may already be waiting.
        if device._process is not None:
            device.stop_uiautomator(wait=True)


def drive_ui(device, adb, args, on, before_input):
    command = args.command
    if command == "state":
        info = device.info
        ime = adb.shell("dumpsys input_method", timeout=10)
        keyboard = re.search(r"\b(?:mInputShown|inputShown)=(true|false)", ime)
        return {
            "screenOn": info["screenOn"],
            "app": info["currentPackageName"],
            "keyboard": keyboard[1] == "true" if keyboard else None,
        }
    if command == "wait":
        selector = json.loads(args.until)["see"]
        start = time.monotonic()
        while not elements(device, selector):
            if time.monotonic() - start >= 10:
                raise ValueError("not_reached")
            time.sleep(0.2)
        return {"ms": round((time.monotonic() - start) * 1000)}

    rows = elements(device, on)
    if command == "find":
        return public(one(rows))
    if command == "ui":
        return {
            "elements": [public(r) for r in rows if on or r["text"] or r["desc"] or r["clickable"]]
        }
    if command == "tap":
        target = one(rows)
        method, params = "click", target["center"]
    elif command == "set-text":
        target = one(
            rows if on else [r for r in rows if r["focused"] and r["klass"].endswith("EditText")]
        )
        fields = dict(className=target["klass"])
        if target["full_id"]:
            fields["resourceId"] = target["full_id"]
        for i in range(device.jsonrpc.count(Selector(**fields))):
            sel = Selector(**fields, instance=i)
            info = device.jsonrpc.objInfo(sel)
            if any(
                [rect[k] for k in ("left", "top", "right", "bottom")] == target["bounds"]
                for rect in (info.get("bounds"), info.get("visibleBounds"))
                if rect
            ):
                break
        else:
            raise ValueError("target_moved")
        method, params = "setText", [sel, args.words[0]]
    else:
        raise ValueError("unknown command")
    before_input()
    # The SDK's public JSON-RPC wrapper retries on transport failure. An input must go out only once.
    if (
        _jsonrpc_call(adb, DEFAULT_SERVER_PORT, method, params, timeout=10, print_request=False)
        is not True
    ):
        raise ValueError("Android refused " + method)
    return public(target) if command == "tap" else None


def migrate_file_lease(store, serial):
    root = Path(
        os.environ.get("AGENT_PHONE_LOCAL_STATE", Path.home() / ".agent-phone/local-leases")
    )
    path = root / hashlib.sha256(serial.encode()).hexdigest()
    if not path.is_file():
        return
    with path.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not path.is_file():
            return
        lease = json.loads(path.read_text())
        remaining = math.ceil(lease["until"] - time.time())
        if remaining > 0:
            lease.update(owner=store.user, since=lease["until"] - 600)
            store.db.set(store.lease_key(serial), json.dumps(lease), ex=remaining, nx=True)
        path.unlink()


def parse(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument("command")
    parser.add_argument("serial", nargs="?")
    for opt in ("why", "on", "task", "until"):
        parser.add_argument("--" + opt)
    # The TypeScript CLI sends free text after --, so leading dashes are literal.
    split = argv.index("--") if "--" in argv else len(argv)
    args = parser.parse_args(argv[:split])
    args.words = argv[split + 1 :]
    return args


def adb_client():
    exe = shutil.which("adb") or Path.home() / "Library/Android/sdk/platform-tools/adb"
    if not Path(exe).is_file():
        raise ValueError("Install Android SDK Platform-Tools or add adb to PATH.")
    host_env = {
        k: v
        for k, v in os.environ.items()
        if k not in ("ADB_SERVER_SOCKET", "ANDROID_ADB_SERVER_ADDRESS", "ANDROID_ADB_SERVER_PORT")
    }
    subprocess.run([exe, "-P", "5037", "start-server"], check=True, timeout=12, env=host_env)
    return adbutils.AdbClient(host="127.0.0.1", port=5037, socket_timeout=15)


def device_action(store, adb, args, lock, **details):
    def before_input():
        # Looking up a control can take time. Recheck both reservations before sending the input.
        lock.reacquire()
        store.require_owner(args.serial)

    def perform():
        store.require_owner(args.serial)
        if adb.get_state() != "device":
            raise ValueError("device_not_ready")
        return drive(adb, args, before_input)

    action = "snapshot" if args.command == "ui" else args.command
    if args.command in ("open", "key", "swipe") or (args.command == "tap" and not args.on):
        details["arguments"] = args.words
    if args.on and "id" in json.loads(args.on):
        details["targetId"] = json.loads(args.on)["id"]
    return store.audit(args.serial, action, args.why, perform, **details)


class RunFailed(Exception):
    def __init__(self, run_id, step, error):
        self.result = {
            "error": str(error),
            "runId": run_id,
            "failedStep": step,
            "completed": step - 1,
        }


def run_routine(store, adb, args, lock):
    name = args.words[0]
    routine = store.routine(name)
    run_id = uuid4().hex

    def execute():
        store.require_owner(args.serial)
        for index, (command, *options) in enumerate(routine["commands"], 1):
            try:
                # Reserve time for this step without taking over an expired lease.
                lock.reacquire()
                lease = store.require_owner(args.serial)
                store.reserve(args.serial, lease["task"])
                step = parse([command, args.serial, "--why=" + args.why, *options])
                last = device_action(store, adb, step, lock, runId=run_id, routine=name, step=index)
            except Exception as error:
                raise RunFailed(run_id, index, error) from error
        return {
            "runId": run_id,
            "routine": name,
            "completed": len(routine["commands"]),
            "lastResult": last,
        }

    return store.audit(args.serial, "routine-run", args.why, execute, runId=run_id, routine=name)


def main(argv):
    args = parse(argv)
    store = Store()
    if args.command == "history":
        return store.history(args.serial)
    if args.command == "routine-list":
        return {"routines": sorted(store.db.hkeys(store.prefix + "routines"))}
    if args.command == "routine-show":
        return {"name": args.serial, "steps": store.routine(args.serial)["steps"]}
    if args.command == "routine-save":
        return store.save(args.serial, json.load(sys.stdin))

    if args.command == "phones":
        devices = adb_client().list(extended=True)
        for device in devices:
            migrate_file_lease(store, device.serial)
        return store.inventory(devices)

    serial = args.serial
    lock = store.db.lock(store.prefix + "operation:" + serial, timeout=600, blocking=False)
    if not lock.acquire():
        raise ValueError("device_busy")
    try:
        migrate_file_lease(store, serial)
        if args.command == "release":

            def release():
                if store.lease(serial):
                    store.require_owner(serial)
                    store.db.delete(store.lease_key(serial))
                return {}

            return store.audit(serial, "release", "", release)
        adb = adb_client().device(serial=serial)
        if args.command == "lease":

            def reserve():
                if adb.get_state() != "device":
                    raise ValueError("device_not_ready")
                return store.reserve(serial, args.task)

            return store.audit(serial, "lease", args.task, reserve)
        if args.command == "routine-run":
            return run_routine(store, adb, args, lock)
        value = device_action(store, adb, args, lock)
        if args.command in ("ui", "find", "screenshot"):
            return value
        return {"action": args.command, "answer": value}
    finally:
        lock.release()


if __name__ == "__main__":
    try:
        result = main(sys.argv[1:])
        print(
            json.dumps(
                result if sys.argv[1] == "find" else {"ok": True, **result}, ensure_ascii=False
            )
        )
    except MatchError as error:
        print(json.dumps({"ok": False, "error": str(error), "matches": error.matches}))
        sys.exit(1)
    except RunFailed as error:
        print(json.dumps({"ok": False, **error.result}))
        sys.exit(1)
    except RedisError as error:
        print(
            json.dumps({"ok": False, "error": "redis_unavailable", "detail": type(error).__name__})
        )
        sys.exit(1)
    except Exception as error:
        print(json.dumps({"ok": False, "error": str(error)}))
        sys.exit(1)
