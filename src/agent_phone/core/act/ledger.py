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
from pathlib import Path

from agent_phone.core.device import DeviceIdentity
from agent_phone.core.outcome import ErrorCode, Refusal
from agent_phone.core.phone import InputAction, Permit
from agent_phone.core.policy.engine import Grant, Verdict


class Ledger:
    def __init__(self, root: Path, device: DeviceIdentity) -> None:
        self._root = root
        self._device = device
        self._open: list[Permit] = []

    def epoch(self) -> int:
        """A ledger file from another boot is restarted: refs from that boot already fail on
        their boot id, so its epoch carries no information. A file that cannot be read is
        refused, because restarting it could make a spent ref current again."""
        path = self._root / "devices" / self._device.serial / "ledger.json"
        try:
            document = json.loads(path.read_text())
            boot_id, epoch = document["boot_id"], int(document["epoch"])
        except FileNotFoundError:
            return 0
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise Refusal(
                ErrorCode.INTERNAL,
                f"The ledger file {path} cannot be read. Delete it, and take new snapshots, "
                "because every ref made before is gone.",
            ) from error
        return epoch if boot_id == self._device.boot_id else 0

    def spend(self, action: InputAction, verdict: Verdict, grant: Grant) -> Permit:
        # TODO: e = epoch() + 1; write {"boot_id", "epoch": e} to a temp file, fsync, rename,
        # fsync the directory; then permit = Permit(self._device, e, action, verdict, grant);
        # self._open.append(permit); return permit
        raise NotImplementedError

    def refund(self, permit: Permit) -> None:
        """Put the epoch back to `permit.epoch - 1`. Refunding twice, or a permit that is not the
        newest spent one, is a bug and raises INTERNAL instead of rewinding past another input."""
        raise NotImplementedError

    def unrefunded(self) -> bool:
        """True when this process spent a permit it did not refund. The CLI's last-resort error
        handler reports `delivery_uncertain` then, because it cannot know how far input got."""
        raise NotImplementedError
