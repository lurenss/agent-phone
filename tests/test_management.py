import concurrent.futures
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from redis import Redis

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import local
from store import Store


class ManagementTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        folder = tempfile.TemporaryDirectory()
        cls.addClassCleanup(folder.cleanup)
        socket = Path(folder.name) / "redis.sock"
        server = subprocess.Popen(
            [
                "redis-server",
                "--port",
                "0",
                "--unixsocket",
                str(socket),
                "--save",
                "",
                "--appendonly",
                "no",
                "--dir",
                folder.name,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        cls.addClassCleanup(server.wait, 5)
        cls.addClassCleanup(server.terminate)
        cls.url = f"unix://{socket}"
        cls.redis = Redis.from_url(cls.url)
        for _ in range(100):
            if socket.exists() and server.poll() is None:
                if cls.redis.ping():
                    break
            time.sleep(0.02)
        else:
            raise RuntimeError("Test Redis did not start")

    def setUp(self):
        self.redis.flushdb()  # The suite owns this temporary Unix socket.
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.enterContext(
            patch.dict(
                os.environ,
                AGENT_PHONE_REDIS_URL=self.url,
                AGENT_PHONE_LOCAL_STATE=folder.name,
                AGENT_PHONE_OWNER="alice",
            )
        )
        self.client = self.enterContext(patch.object(local, "adb_client")).return_value
        self.client.device.return_value.get_state.return_value = "device"

    def test_inventory_keeps_disconnected_devices_but_counts_only_ready_devices(self):
        def device(serial, state):
            return SimpleNamespace(serial=serial, state=state, tags={"model": "test"})

        self.client.list.return_value = [
            device("one", "device"),
            device("two", "device"),
            device("three", "unauthorized"),
        ]
        local.main(["lease", "one", "--task=test"])
        initial = local.main(["phones"])
        self.assertEqual(initial["counts"], {"known": 3, "active": 2, "available": 1, "busy": 1})
        self.assertEqual(initial["phones"][0]["lease"]["owner"], Store().owner)
        self.client.list.return_value = [device("two", "offline")]
        later = local.main(["phones"])
        self.assertEqual(later["counts"]["active"], 0)
        self.assertEqual(
            {p["serial"]: p["state"] for p in later["phones"]},
            {"one": "disconnected", "two": "offline", "three": "disconnected"},
        )

    def test_two_operators_race_and_only_the_winner_can_act_or_release(self):
        def cli_process(owner):
            code = (
                "import sys; sys.path.insert(0, 'src'); import local; from unittest.mock import Mock; "
                "client=Mock(); client.device.return_value.get_state.return_value='device'; "
                "local.adb_client=lambda:client; "
                "print(local.main(['lease','one','--task=race'])['lease']['owner'])"
            )
            return subprocess.run(
                [sys.executable, "-c", code],
                env={**os.environ, "AGENT_PHONE_OWNER": owner},
                cwd=Path(__file__).resolve().parents[1],
                capture_output=True,
                text=True,
            )

        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            results = list(pool.map(cli_process, ["alice", "bob"]))
        winners = [r for r in results if r.returncode == 0]
        self.assertEqual(len(winners), 1)
        owner = winners[0].stdout.strip().split("/")[-1]
        os.environ["AGENT_PHONE_OWNER"] = "bob" if owner == "alice" else "alice"
        with patch.object(local, "drive") as drive:
            for args in (["key", "one", "--why=test", "--", "BACK"], ["release", "one"]):
                with self.assertRaisesRegex(ValueError, "leased_by_another_owner"):
                    local.main(args)
            drive.assert_not_called()
        self.redis.pexpire(Store().lease_key("one"), 1)
        time.sleep(0.02)
        self.assertEqual(
            local.main(["lease", "one", "--task=new"])["lease"]["owner"], Store().owner
        )

    def test_legacy_lease_preserves_expiry_and_original_account(self):
        path = self.root / hashlib.sha256(b"one").hexdigest()
        expiry = time.time() + 35
        path.write_text(json.dumps({"task": "existing", "until": expiry}))
        with self.assertRaisesRegex(ValueError, "leased_by_another_owner"):
            local.main(["release", "one"])
        lease = Store().lease("one")
        self.assertEqual(lease["owner"], Store().user)
        self.assertEqual(lease["until"], expiry)
        self.assertFalse(path.exists())

    def test_failed_run_audits_each_attempt_and_stops_before_the_next_step(self):
        store = Store()
        store.save(
            "test",
            {
                "steps": [["state"], ["key", "BACK"], ["key", "HOME"]],
                "commands": [["state"], ["key", "--", "BACK"], ["key", "--", "HOME"]],
            },
        )
        local.main(["lease", "one", "--task=test"])
        with patch.object(local, "drive", side_effect=[{}, ValueError("not_found")]) as drive:
            with self.assertRaises(local.RunFailed) as caught:
                local.main(["routine-run", "one", "--why=test", "--", "test"])
            self.assertEqual(drive.call_count, 2)
        outcome = caught.exception.result
        self.assertEqual((outcome["completed"], outcome["failedStep"]), (1, 2))
        events = local.main(["history", "one"])["events"]
        self.assertEqual(
            [(e["step"], e["status"]) for e in reversed(events) if "step" in e],
            [(1, "started"), (1, "ok"), (2, "started"), (2, "error")],
        )
        self.assertTrue(all(e["owner"] == store.owner for e in events))
        self.assertTrue(all(e["runId"] == outcome["runId"] for e in events if "step" in e))

    def test_running_routine_blocks_other_inputs_even_from_the_same_owner(self):
        store = Store()
        store.save("inspect", {"steps": [["state"]], "commands": [["state"]]})
        local.main(["lease", "one", "--task=inspect"])

        def check_lock(adb, args, before_input):
            with self.assertRaisesRegex(ValueError, "device_busy"):
                local.main(["key", "one", "--why=interrupt", "--", "HOME"])
            return {"app": "demo.app"}

        with patch.object(local, "drive", side_effect=check_lock):
            result = local.main(["routine-run", "one", "--why=inspect", "--", "inspect"])
        self.assertEqual(result["lastResult"], {"app": "demo.app"})
        self.assertEqual(result["completed"], 1)

    def test_no_input_if_redis_is_unavailable(self):
        from redis.exceptions import ConnectionError

        with patch.dict(
            os.environ, AGENT_PHONE_REDIS_URL="unix:///nonexistent-agent-phone-test.sock"
        ):
            with patch.object(local, "drive") as drive, self.assertRaises(ConnectionError):
                local.main(["key", "one", "--why=test", "--", "BACK"])
            drive.assert_not_called()
