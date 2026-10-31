"""The first screen read of a one-shot command, taken while the device facts are still being read.

A warm `snapshot` spends 151 ms on the facts shell and 106 ms on the dump of the Instagram feed
(A5-4), one after the other. The dump needs the server and not the facts, so it runs beside the
shell and the command waits for the slower of the two. The cost is that the dump is read up to
the length of the facts shell before the command looks at it, which the plan accepts (A5-2).
That is only right for a caller that reads once, straight after it opens the phone. A session
that does other things first must not be handed a screen from before them, so the dump is used
only within `MAX_AGE_S`, and only the first read ever can use it.
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from agent_phone.core.device import DeviceInfo
from agent_phone.core.outcome import Refusal
from agent_phone.core.wait.clock import Clock

MAX_AGE_S = 1.0


@dataclass(frozen=True, slots=True)
class FirstRead:
    """The dump text, or the refusal that the read ended in. A refusal is kept and raised by the
    first `read()`, where it would have been raised without the overlap."""

    xml: str | None
    refusal: Refusal | None
    taken_at: float

    def text(self) -> str:
        if self.refusal is not None:
            raise self.refusal
        assert self.xml is not None
        return self.xml


def overlap(
    facts: Callable[[], DeviceInfo], prepare: Callable[[], None], dump: Callable[[], str], clock: Clock
) -> tuple[DeviceInfo, FirstRead]:
    """Run `facts` on a thread, and `prepare` then `dump` here. A refusal from `prepare` or from
    `facts` is raised once both have finished, so no thread outlives the call. A refusal from
    `dump` is kept in the `FirstRead`."""
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(facts)
        prepare()
        try:
            xml, refusal = dump(), None
        except Refusal as raised:
            xml, refusal = None, raised
        taken_at = clock.now()
        info = pending.result()
    return info, FirstRead(xml, refusal, taken_at)
