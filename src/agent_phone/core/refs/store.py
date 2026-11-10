"""Snapshots on disk, so refs outlive the process that printed them.

Layout under the state root (default `~/.agent-phone/`):

    devices/<serial>/snapshots/<id>.json   one immutable file per snapshot, written once
    devices/<serial>/latest                 id of the device's newest snapshot
    devices/<serial>/lock                   held while a process drives the device (A3-4)

Each device writes only under its own directory, so two processes driving two devices never
write the same file, and one device lock (A3-4) serializes writers within a device. Lookup by
id searches every device directory, which is how a ref used with the wrong `-d` is recognised
as another device's instead of reported as missing. Ids are drawn at random and created with
O_EXCL after a cross-directory existence check; a lookup that finds two files refuses.

The JSON schema is private to this module.
"""

from __future__ import annotations

import fcntl
import json
import os
import secrets
import types
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any, NewType, Union, get_args, get_origin, get_type_hints

from agent_phone.core.device import Serial
from agent_phone.core.outcome import ErrorCode, Refusal
from agent_phone.core.refs.fingerprint import Fingerprint
from agent_phone.core.snapshot.snapshot import ID_ALPHABET, ID_LENGTH, Snapshot, SnapshotId
from agent_phone.core.wait.clock import Clock
from agent_phone.core.wait.until import until

RETAINED_PER_DEVICE = 64
FORMAT = 2
LOCK_WAIT_S = 10.0


class SnapshotStore:
    def __init__(self, root: Path) -> None:
        self._root = root

    def new_id(self, serial: Serial) -> SnapshotId:
        while True:
            id = SnapshotId("".join(secrets.choice(ID_ALPHABET) for _ in range(ID_LENGTH)))
            if not self._files(id):
                return id

    def record(self, snapshot: Snapshot) -> None:
        """Write the file (temp + rename), point `latest` at it, prune the device's oldest
        files beyond RETAINED_PER_DEVICE. Recording the same snapshot twice is a no-op."""
        directory = self._device(snapshot.device.serial) / "snapshots"
        path = directory / f"{snapshot.id}.json"
        text = encode(snapshot)
        if path.exists() and path.read_text() == text:
            return
        if self._files(snapshot.id):
            raise Refusal(ErrorCode.INTERNAL, f"Snapshot id {snapshot.id} already names another snapshot.")
        directory.mkdir(parents=True, exist_ok=True)
        write_atomically(path, text)
        write_atomically(self._device(snapshot.device.serial) / "latest", snapshot.id)
        older = sorted((p for p in directory.glob("*.json") if p != path), key=lambda p: p.stat().st_mtime_ns)
        for stale in older[: max(0, len(older) - (RETAINED_PER_DEVICE - 1))]:
            stale.unlink(missing_ok=True)

    def load(self, id: SnapshotId) -> Snapshot:
        """Raise `Refusal(SNAPSHOT_NOT_FOUND)` when no device directory has it (never made, or
        pruned)."""
        return read(self._one(id), id)

    def latest(self, serial: Serial) -> Snapshot | None:
        try:
            id = SnapshotId((self._device(serial) / "latest").read_text().strip())
        except FileNotFoundError:
            return None
        path = self._device(serial) / "snapshots" / f"{id}.json"
        return read(path, id) if path.exists() else None

    def device_of(self, id: SnapshotId) -> Serial | None:
        """Which device directory holds `id`, so the CLI can pick the device from a ref."""
        if not self._files(id):
            return None
        return Serial(self._one(id).parent.parent.name)

    def lock(
        self, serial: Serial, clock: Clock, wait_s: float = LOCK_WAIT_S, command: str = ""
    ) -> DeviceLock:
        return DeviceLock(self._device(serial) / "lock", serial, clock, wait_s, command)

    def _device(self, serial: Serial) -> Path:
        return self._root / "devices" / serial

    def _files(self, id: SnapshotId) -> list[Path]:
        devices = self._root / "devices"
        if not devices.is_dir():
            return []
        return [path for d in sorted(devices.iterdir()) if (path := d / "snapshots" / f"{id}.json").is_file()]

    def _one(self, id: SnapshotId) -> Path:
        files = self._files(id)
        if not files:
            raise Refusal(
                ErrorCode.SNAPSHOT_NOT_FOUND,
                f"No snapshot {id} is stored. It was never taken here, or it is older than the "
                f"newest {RETAINED_PER_DEVICE} of its device.",
            )
        if len(files) > 1:
            raise Refusal(ErrorCode.INTERNAL, f"Snapshot id {id} is stored for more than one device.")
        return files[0]


class DeviceLock:
    """The claim on one device. Only one process drives a device at a time (A3-4): the server
    allows one UiAutomation client, and refs and the ledger assume one writer.

    It is an advisory `flock` on a file that nobody deletes, so the kernel drops it when the
    holder dies and no crash leaves a stale lock. The holder writes its pid and command into
    the file only so that a refused process can say who is in the way.
    """

    def __init__(self, path: Path, serial: Serial, clock: Clock, wait_s: float, command: str) -> None:
        self._path = path
        self._serial = serial
        self._clock = clock
        self._wait_s = wait_s
        self._command = command
        self._fd: int | None = None

    def __enter__(self) -> DeviceLock:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self._path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            if until(self._clock, lambda: self._try(fd), self._wait_s) is None:
                raise Refusal(
                    ErrorCode.DEVICE_BUSY,
                    f"Another process is driving {self._serial}{self._holder(fd)}. "
                    f"It did not let go within {self._wait_s:g} s.",
                    {"serial": self._serial, "waited_s": self._wait_s},
                )
            os.ftruncate(fd, 0)
            os.write(fd, f"{os.getpid()} {self._command}\n".encode())
        except BaseException:
            os.close(fd)
            raise
        self._fd = fd
        return self

    def __exit__(self, *exc: object) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None

    @staticmethod
    def _try(fd: int) -> bool | None:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return None
        return True

    @staticmethod
    def _holder(fd: int) -> str:
        text = os.pread(fd, 200, 0).decode(errors="replace").strip()
        return f" (pid {text})" if text else ""


def write_atomically(path: Path, text: str) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w") as file:
        file.write(text)
        file.flush()
        os.fsync(file.fileno())
    os.replace(temporary, path)


def read(path: Path, id: SnapshotId) -> Snapshot:
    try:
        return decode(path.read_text())
    except (ValueError, KeyError, TypeError) as error:
        raise Refusal(
            ErrorCode.SNAPSHOT_NOT_FOUND,
            f"Snapshot {id} is stored in a form this agent-phone cannot read. Take a new snapshot.",
        ) from error


def encode(snapshot: Snapshot) -> str:
    return json.dumps(
        {"format": FORMAT, "snapshot": to_json(snapshot)}, ensure_ascii=False, separators=(",", ":")
    )


def decode(text: str) -> Snapshot:
    document = json.loads(text)
    if document.get("format") != FORMAT:
        raise ValueError(f"snapshot format {document.get('format')!r}")
    return from_json(Snapshot, document["snapshot"])


def to_json(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: to_json(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, tuple):
        return [to_json(item) for item in value]
    if isinstance(value, frozenset):
        return sorted(to_json(item) for item in value)
    if isinstance(value, Mapping):
        return {str(key): to_json(item) for key, item in value.items()}
    return value


def from_json(kind: Any, data: Any) -> Any:
    """The inverse of `to_json`, driven by the dataclass annotations of `kind`."""
    origin = get_origin(kind)
    if origin in (Union, types.UnionType):
        if data is None:
            return None
        (inner,) = (arg for arg in get_args(kind) if arg is not type(None))
        return from_json(inner, data)
    if origin is tuple:
        item = get_args(kind)[0]
        return tuple(from_json(item, value) for value in data)
    if origin is frozenset:
        item = get_args(kind)[0]
        return frozenset(from_json(item, value) for value in data)
    if origin is Mapping:
        key, item = get_args(kind)
        return {from_json(key, k): from_json(item, v) for k, v in data.items()}
    if isinstance(kind, NewType):
        return from_json(kind.__supertype__, data)
    if isinstance(kind, type) and issubclass(kind, Enum):
        return kind(data)
    if is_dataclass(kind):
        hints = get_type_hints(kind, localns={"Fingerprint": Fingerprint})
        return kind(**{f.name: from_json(hints[f.name], data[f.name]) for f in fields(kind)})
    if kind is int:
        return int(data)
    return data
