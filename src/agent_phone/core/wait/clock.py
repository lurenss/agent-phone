"""Time, behind a seam. `core/wait/` is the one place `time.sleep` may appear (ruff TID251)."""

from __future__ import annotations

import time
from typing import Protocol


class Clock(Protocol):
    def now(self) -> float:
        """Monotonic seconds."""
        ...

    def pause(self, seconds: float) -> None: ...


class SystemClock:
    def now(self) -> float:
        return time.monotonic()

    def pause(self, seconds: float) -> None:
        time.sleep(seconds)


POLL_GAP_S = 0.05
"""A server dump already takes ~150 ms (A2-1, A2-2), so polls need almost no gap of their own."""
