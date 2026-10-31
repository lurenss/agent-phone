"""A snapshot: one observation of one surface on one device boot, at one ledger epoch.

The same frozen value is printed to the caller, persisted by the store and read back by the
next process. It carries the lines the agent saw and the fingerprints its refs resolve with,
so nothing has to be recomputed or kept in sync.

Ref text form: `@<snapshot id>:e<N>`, for example `@k3x9q:e12`. A bare `e12` or `@e12` is
INVALID_ARGS. Snapshot ids are five random Crockford base32 characters in lower case, unique
across every device directory of the store (`refs/store.py`), so the id alone names the device
that made it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, NewType

from agent_phone.core.device import DeviceIdentity, Package
from agent_phone.core.query import Query
from agent_phone.core.screen import WindowKind
from agent_phone.core.snapshot.surface import OtherWindow
from agent_phone.core.snapshot.view import Line, Mode

if TYPE_CHECKING:
    from agent_phone.core.refs.fingerprint import Fingerprint

SnapshotId = NewType("SnapshotId", str)


@dataclass(frozen=True, slots=True)
class RefToken:
    snapshot: SnapshotId
    number: int

    @staticmethod
    def parse(text: str) -> RefToken:
        """Raise `Refusal(INVALID_ARGS)` for anything but `@<5 base32>:e<positive int>`."""
        raise NotImplementedError

    def __str__(self) -> str:
        return f"@{self.snapshot}:e{self.number}"


class SettleState(Enum):
    """SETTLED: two consecutive reads gave the same lines. UNSETTLED: the settle deadline passed
    first, and this is the last read. UNCHECKED: one read, no settle asked (A2-5)."""

    SETTLED = "settled"
    UNSETTLED = "unsettled"
    UNCHECKED = "unchecked"


@dataclass(frozen=True, slots=True)
class Snapshot:
    id: SnapshotId
    device: DeviceIdentity
    epoch: int
    package: Package
    window_kind: WindowKind
    mode: Mode
    settled: SettleState
    keyboard: bool
    dialog: bool
    others: tuple[OtherWindow, ...]
    toasts: tuple[str, ...]
    lines: tuple[Line, ...]
    fingerprints: Mapping[int, Fingerprint]
    truncated: int

    def ref(self, number: int) -> RefToken:
        return RefToken(self.id, number)

    def pick(self, query: Query, below: Query | None = None) -> RefToken:
        """The one ref line matching `query`, optionally below the first line matching `below`.

        Strict like resolution: no match is `Refusal(NOT_FOUND)`, several are
        `Refusal(AMBIGUOUS_TARGET)` listing their refs. `query.resource_id` matches a line's
        `id_hint`, which is printed only for nameless lines.
        """
        raise NotImplementedError
