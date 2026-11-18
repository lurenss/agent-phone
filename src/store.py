"""Redis state for one Mac's Android devices."""

import json
import os
import pwd
import socket
import time
from uuid import uuid4

from redis import Redis
from redis.backoff import NoBackoff
from redis.retry import Retry


class Store:
    def __init__(self):
        self.db = Redis.from_url(
            os.environ.get("AGENT_PHONE_REDIS_URL", "redis://127.0.0.1:6379/0"),
            decode_responses=True,
            socket_connect_timeout=3,
            socket_timeout=5,
            retry=Retry(NoBackoff(), 0),
        )
        self.prefix = f"agent-phone:{socket.gethostname()}:"
        self.user = pwd.getpwuid(os.getuid()).pw_name
        label = os.environ.get("AGENT_PHONE_OWNER", "").strip()
        if len(label) > 80 or any(ord(c) < 32 for c in label):
            raise ValueError("invalid_owner")
        self.owner = f"{self.user}/{label}" if label else self.user

    def lease_key(self, serial):
        return self.prefix + "lease:" + serial

    def lease(self, serial):
        data = self.db.get(self.lease_key(serial))
        return json.loads(data) if data else None

    def reserve(self, serial, task):
        current = self.lease(serial)
        if current and current["owner"] != self.owner:
            raise ValueError("leased_by_another_owner")
        now = time.time()
        lease = {
            "owner": self.owner,
            "task": task,
            "since": current["since"] if current else now,
            "until": now + 600,
        }
        self.db.set(self.lease_key(serial), json.dumps(lease), ex=600)
        return {"lease": lease, "renewed": current is not None}

    def require_owner(self, serial):
        lease = self.lease(serial)
        if not lease:
            raise ValueError("not_leased")
        if lease["owner"] != self.owner:
            raise ValueError("leased_by_another_owner")
        return lease

    def inventory(self, devices):
        now = time.time()
        live = {d.serial: d for d in devices}
        key = self.prefix + "inventory"
        with self.db.pipeline() as pipe:
            for serial, device in live.items():
                pipe.hset(
                    key,
                    serial,
                    json.dumps({"model": device.tags.get("model", ""), "lastSeen": now}),
                )
            known = pipe.hgetall(key).execute()[-1]
        serials = sorted(known)
        leases = self.db.mget([self.lease_key(s) for s in serials]) if serials else []
        phones = []
        for serial, lease in zip(serials, leases):
            state = live[serial].state if serial in live else "disconnected"
            phones.append(
                {
                    "serial": serial,
                    **json.loads(known[serial]),
                    "state": state,
                    "healthy": state == "device",
                    "lease": json.loads(lease) if lease else None,
                }
            )
        active = sum(p["healthy"] for p in phones)
        busy = sum(p["healthy"] and p["lease"] is not None for p in phones)
        return {
            "phones": phones,
            "counts": {
                "known": len(phones),
                "active": active,
                "busy": busy,
                "available": active - busy,
            },
        }

    def routine(self, name):
        data = self.db.hget(self.prefix + "routines", name)
        if data is None:
            raise ValueError("routine_not_found")
        return json.loads(data)

    def save(self, name, definition):
        self.db.hset(self.prefix + "routines", name, json.dumps(definition))
        return {"name": name, "steps": definition["steps"]}

    def record(self, serial, event):
        self.db.xadd(
            self.prefix + "history:" + serial,
            {"event": json.dumps(event)},
            maxlen=2000,
            approximate=False,
        )

    def audit(self, serial, action, why, operation, **details):
        event = {
            "actionId": uuid4().hex,
            "owner": self.owner,
            "serial": serial,
            "action": action,
            "why": why,
            **details,
        }
        self.record(serial, {**event, "status": "started"})
        try:
            result = operation()
        except Exception as error:
            # Error messages from an Android library can include input text.
            reason = (
                str(error)
                if isinstance(error, ValueError) and str(error).isidentifier()
                else type(error).__name__
            )
            self.record(serial, {**event, "status": "error", "error": reason})
            raise
        self.record(serial, {**event, "status": "ok"})
        return result

    def history(self, serial):
        rows = self.db.xrevrange(self.prefix + "history:" + serial, count=100)
        return {
            "events": [
                {"id": key, "at": int(key.split("-")[0]) / 1000, **json.loads(row["event"])}
                for key, row in rows
            ]
        }
