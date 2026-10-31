"""Snapshots on disk, so refs outlive the process that printed them.

Layout under the state root (default `~/.agent-phone/`):

    devices/<serial>/snapshots/<id>.json   one immutable file per snapshot, written once
    devices/<serial>/latest                 id of the device's newest snapshot

Each device writes only under its own directory, so two processes driving two devices never
write the same file, and one device lock (A3-4) serializes writers within a device. Lookup by
id searches every device directory, which is how a ref used with the wrong `-d` is recognised
as another device's instead of reported as missing. Ids are drawn at random and created with
O_EXCL after a cross-directory existence check; a lookup that finds two files refuses.

The JSON schema is private to this module.
"""

from __future__ import annotations

from pathlib import Path

from agent_phone.core.device import Serial
from agent_phone.core.snapshot.snapshot import Snapshot, SnapshotId

RETAINED_PER_DEVICE = 64


class SnapshotStore:
    def __init__(self, root: Path) -> None:
        self._root = root

    def new_id(self, serial: Serial) -> SnapshotId:
        raise NotImplementedError

    def record(self, snapshot: Snapshot) -> None:
        """Write the file (temp + rename), point `latest` at it, prune the device's oldest
        files beyond RETAINED_PER_DEVICE. Recording the same snapshot twice is a no-op."""
        raise NotImplementedError

    def load(self, id: SnapshotId) -> Snapshot:
        """Raise `Refusal(SNAPSHOT_NOT_FOUND)` when no device directory has it (never made, or
        pruned)."""
        raise NotImplementedError

    def latest(self, serial: Serial) -> Snapshot | None:
        raise NotImplementedError

    def device_of(self, id: SnapshotId) -> Serial | None:
        """Which device directory holds `id`, so the CLI can pick the device from a ref."""
        raise NotImplementedError
