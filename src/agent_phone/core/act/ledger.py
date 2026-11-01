"""The input ledger: one epoch counter per device, and the only place a `Permit` is made.

The epoch is the single source of truth behind the retry rule. Every snapshot records the epoch
it was taken at. Spending a permit advances the epoch and writes it to disk before the permit
is returned, so the input cannot leave before every older ref is spent. If the process dies
after the spend, the refs stay spent, and the caller has to look again. That is the safe side.

A refund puts the epoch back. act() refunds only on `NotSent`, the one case where the backend
proved nothing left, which is why `not_delivered` is the only disposition after which the
same command works again.

    devices/<serial>/ledger.json   {"boot_id": "...", "epoch": 41}

Written only by this class, under the device lock.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from agent_phone.core.device import DeviceIdentity
from agent_phone.core.outcome import ErrorCode, Refusal
from agent_phone.core.phone import InputAction, Permit
from agent_phone.core.policy.engine import Grant, Verdict
from agent_phone.core.refs.store import write_atomically

UNREFUNDED: list[Permit] = []
"""Every permit this process spent and did not refund, across ledgers. The CLI's last-resort
handler reads it through `unrefunded()`, because an exception that escaped a command can no
longer reach the ledger that spent the permit."""


class Ledger:
    def __init__(self, root: Path, device: DeviceIdentity) -> None:
        self._path = root / "devices" / device.serial / "ledger.json"
        self._device = device
        self._open: list[Permit] = []

    def epoch(self) -> int:
        """A ledger file from another boot is restarted: refs from that boot already fail on
        their boot id, so its epoch carries no information. A file that cannot be read is
        refused, because restarting it could make a spent ref current again."""
        try:
            document = json.loads(self._path.read_text())
            boot_id, epoch = document["boot_id"], int(document["epoch"])
        except FileNotFoundError:
            return 0
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise Refusal(
                ErrorCode.INTERNAL,
                f"The ledger file {self._path} cannot be read. Delete it, and take new snapshots, "
                "because every ref made before is gone.",
            ) from error
        return epoch if boot_id == self._device.boot_id else 0

    def spend(self, action: InputAction, verdict: Verdict, grant: Grant) -> Permit:
        epoch = self.epoch() + 1
        self._write(epoch)
        permit = Permit(self._device, epoch, action, verdict, grant)
        self._open.append(permit)
        UNREFUNDED.append(permit)
        return permit

    def refund(self, permit: Permit) -> None:
        """Put the epoch back to `permit.epoch - 1`. Refunding twice, or a permit that is not the
        newest spent one, is a bug and raises INTERNAL instead of rewinding past another input."""
        if not self._open or self._open[-1] is not permit or self.epoch() != permit.epoch:
            raise Refusal(
                ErrorCode.INTERNAL,
                f"A refund of epoch {permit.epoch} does not match the newest spend of the ledger. "
                "Nothing was rewound.",
            )
        self._write(permit.epoch - 1)
        self._open.pop()
        UNREFUNDED.remove(permit)

    def _write(self, epoch: int) -> None:
        """Temp file, fsync, rename, then fsync the directory, so the new epoch is on disk before
        the caller goes on."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        write_atomically(self._path, json.dumps({"boot_id": self._device.boot_id, "epoch": epoch}))
        directory = os.open(self._path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)


def unrefunded() -> bool:
    """True when this process spent a permit it did not refund. The CLI's last-resort error
    handler reports `delivery_uncertain` then, because it cannot know how far input got."""
    return bool(UNREFUNDED)
