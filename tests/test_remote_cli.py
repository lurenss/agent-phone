"""The remote mode from where a user starts it: two environment variables and the `agent-phone`
process. `ssh` is a script on PATH that answers like `phone-host`, and adb is `false`, so nothing
here can reach a host or a phone."""

import json
import os
import sys

from agent_phone.cli import process

J7 = "0a1b2c3d4e5f6a7b"
BENS = {"by": "ben", "task": "schedule reel 12", "held_s": 312, "free_in_s": 95, "mine": False}
LISTED = {
    "v": 1,
    "adb": 41,
    "phones": [
        {"serial": J7, "model": "SM_J730F", "state": "device", "lease": BENS},
        {"serial": "emulator-5554", "model": "sdk_gphone64_arm64", "state": "device", "lease": None},
    ],
}
BUSY = {"v": 1, "ok": False, "error": "busy", "lease": BENS}
SSH = f"""#!/bin/sh
for last; do :; done
echo "$last" >> "$(dirname "$0")/asked"
case "$last" in
  list*) echo '{json.dumps(LISTED)}' ;;
  lease*) echo '{json.dumps(BUSY)}'; exit 1 ;;
esac
"""


def agent_phone(monkeypatch, capsys, root, tmp_path, *argv, task=None):
    (tmp_path / "ssh").write_text(SSH)
    (tmp_path / "ssh").chmod(0o755)
    env = {
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "AGENT_PHONE_REMOTE": "farm",
        "AGENT_PHONE_HOME": str(root),
        "AGENT_PHONE_LOCK_WAIT_S": "0",
        "AGENT_PHONE_TASK": task or "",
        "AGENT_PHONE_PERMISSION_MODE": "",
        "ADB": "false",
    }
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(sys, "argv", ["agent-phone", *argv])
    code = process.main()
    asked = (tmp_path / "asked").read_text().splitlines() if (tmp_path / "asked").exists() else []
    return code, json.loads(capsys.readouterr().out), asked


def test_devices_lists_the_phones_of_the_phone_host_and_who_holds_each(
    monkeypatch, capsys, short_root, tmp_path
):
    code, wire, asked = agent_phone(monkeypatch, capsys, short_root, tmp_path, "devices")
    held, free = wire["data"]["devices"]
    assert code == 0 and (held["serial"], held["ready"], held["lease"]) == (J7, True, BENS)
    assert free["serial"] == "emulator-5554" and "lease" not in free
    assert "adb" in held["problem"], "adb is `false` here, so no facts were read through the host"
    holder = (short_root / "remote" / "holder").read_text().strip()
    assert asked == [f"list --holder {holder}"]


def test_a_phone_another_holder_drives_is_device_busy_with_their_name_and_task(
    monkeypatch, capsys, short_root, tmp_path
):
    code, wire, asked = agent_phone(
        monkeypatch, capsys, short_root, tmp_path, "snapshot", "-d", J7, task="dry run"
    )
    assert code == 1 and (wire["ok"], wire["device"]) == (False, J7)
    assert (wire["delivery"], wire["retry"]) == ("not_delivered", "safe")
    assert wire["error"]["code"] == "DEVICE_BUSY"
    assert wire["error"]["message"] == (
        "ben is driving 0a1b2c3d4e5f6a7b (schedule reel 12). The lease runs out in 95 s unless ben "
        "renews it. This command waited 0 s."
    )
    assert wire["error"]["details"] == {
        "serial": J7,
        "by": "ben",
        "task": "schedule reel 12",
        "free_in_s": 95,
        "waited_s": 0.0,
    }
    assert asked[1].startswith(f"lease {J7} --holder ") and asked[1].endswith(
        "'--task=dry run' --ttl 120 --port 9008"
    )


def test_a_command_that_needs_no_phone_asks_the_host_nothing(monkeypatch, capsys, short_root, tmp_path):
    code, wire, asked = agent_phone(monkeypatch, capsys, short_root / "state", tmp_path, "skills", "list")
    assert code == 0 and wire["ok"] and asked == [] and not (short_root / "state").exists()
