"""Waiting for a condition that the screen does not show: a lock, a server that is starting.

`observe` polls the screen. This polls anything else with the same deadline and the same clock
seam, so no other module needs `time.sleep`.
"""

from __future__ import annotations

from collections.abc import Callable

from agent_phone.core.wait.clock import POLL_GAP_S, Clock


def until[T](
    clock: Clock, attempt: Callable[[], T | None], timeout_s: float, gap_s: float = POLL_GAP_S
) -> T | None:
    """Call `attempt` until it returns something other than None, or `timeout_s` has passed.

    It always calls `attempt` once, even for a timeout of zero. It returns None on timeout.
    """
    deadline = clock.now() + timeout_s
    while True:
        found = attempt()
        if found is not None:
            return found
        if clock.now() >= deadline:
            return None
        clock.pause(gap_s)
