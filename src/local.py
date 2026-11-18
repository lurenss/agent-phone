# /// script
# requires-python = ">=3.11,<3.15"
# dependencies = ["uiautomator2==3.7.1", "adbutils==2.12.0"]
# ///
"""Commands over the Mac's loopback ADB server. One command, one selected serial."""

import argparse
import fcntl
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


def one(rows):
    if len(rows) != 1:
        raise ValueError("ambiguous" if rows else "not_found")
    return rows[0]


def drive(adb, args):
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
        return drive_ui(device, adb, args, on)
    finally:
        # Hold the serial lock until our helper exits. Another CLI process may already be waiting.
        if device._process is not None:
            device.stop_uiautomator(wait=True)


def drive_ui(device, adb, args, on):
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
    # The SDK's public JSON-RPC wrapper retries on transport failure. An input must go out only once.
    if (
        _jsonrpc_call(adb, DEFAULT_SERVER_PORT, method, params, timeout=10, print_request=False)
        is not True
    ):
        raise ValueError("Android refused " + method)
    return public(target) if command == "tap" else None


def lease_path(root, serial):
    return root / hashlib.sha256(serial.encode()).hexdigest()


def active(path):
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        return None
    return data if data["until"] > time.time() else None


def main(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument("command")
    parser.add_argument("serial", nargs="?")
    for opt in ("why", "on", "task", "until"):
        parser.add_argument("--" + opt)
    # The TypeScript CLI sends free text after --, so leading dashes are literal.
    split = argv.index("--") if "--" in argv else len(argv)
    args = parser.parse_args(argv[:split])
    args.words = argv[split + 1 :]
    exe = shutil.which("adb") or Path.home() / "Library/Android/sdk/platform-tools/adb"
    if not Path(exe).is_file():
        raise ValueError("Install Android SDK Platform-Tools or add adb to PATH.")
    host_env = {
        k: v
        for k, v in os.environ.items()
        if k not in ("ADB_SERVER_SOCKET", "ANDROID_ADB_SERVER_ADDRESS", "ANDROID_ADB_SERVER_PORT")
    }
    subprocess.run([exe, "-P", "5037", "start-server"], check=True, timeout=12, env=host_env)
    client = adbutils.AdbClient(host="127.0.0.1", port=5037, socket_timeout=15)
    root = Path(
        os.environ.get("AGENT_PHONE_LOCAL_STATE", Path.home() / ".agent-phone/local-leases")
    )
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if args.command == "phones":
        return {
            "phones": [
                dict(
                    serial=d.serial,
                    state=d.state,
                    model=d.tags.get("model", ""),
                    healthy=d.state == "device",
                    lease=active(lease_path(root, d.serial)),
                )
                for d in client.list(extended=True)
            ]
        }

    path = lease_path(root, args.serial)
    # A persistent lock inode serializes release, renewal and input across CLI processes.
    with path.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if args.command == "release":
            path.unlink(missing_ok=True)
            return {}
        adb = client.device(serial=args.serial)
        if adb.get_state() != "device":
            raise ValueError("device_not_ready")
        if args.command == "lease":
            renewed = active(path) is not None
            lease = {"task": args.task, "until": time.time() + 600}
            staged = path.with_suffix(".tmp")
            staged.write_text(json.dumps(lease))
            staged.replace(path)
            return {"lease": lease, "renewed": renewed}
        if not active(path):
            raise ValueError("not_leased")
        value = drive(adb, args)
        if args.command in ("ui", "screenshot"):
            return value
        return {"action": args.command, "answer": value}


if __name__ == "__main__":
    try:
        print(json.dumps({"ok": True, **main(sys.argv[1:])}, ensure_ascii=False))
    except Exception as error:
        print(json.dumps({"ok": False, "error": str(error)}))
        sys.exit(1)
