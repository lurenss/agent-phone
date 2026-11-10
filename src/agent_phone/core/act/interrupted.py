"""Ending an input's auto-wait when a pop-up is in the way.

A target that a window covers, or that the active window does not hold, is read again until the
request's deadline, because a keyboard that slides away or a screen that loads clears it. A pop-up
the policy recognises (`policy/interrupt.py`) does not clear by itself, so the wait would only
spend its whole timeout and then report a code that does not name the pop-up. This ends it on the
first read that shows one.

Nothing is sent and the epoch stays. The read is recorded as a snapshot, so the refusal carries a
live ref for the pop-up's way out. Whether to click it is the caller's call, through the gate.
"""

from __future__ import annotations

from agent_phone.core.context import Context
from agent_phone.core.outcome import ErrorCode, Refusal
from agent_phone.core.policy.interrupt import interruptions_of
from agent_phone.core.screen import Screen, WindowId
from agent_phone.core.snapshot.capture import capture

COVERED = frozenset({ErrorCode.OCCLUDED, ErrorCode.NOT_FOUND})


def refuse_interrupted(ctx: Context, screen: Screen, target: WindowId | None, waiting: Refusal) -> None:
    """Raise `Refusal(INTERRUPTED)` when `waiting` says the target is covered or not there, and
    the window with input focus is an interruption and is not the target's window. `target` is
    None when the target was not found, and then that window must also be a dialog: a full-screen
    page whose words match a rule may still be loading the target.

    A pop-up that lost focus is on its way out, and a pop-up's own button under the keyboard is
    only covered, so both keep waiting. So does a read with no window to describe."""
    active = screen.active_window()
    if waiting.code not in COVERED or active is None or active.id == target:
        return
    if target is None and active.bounds.fills(screen.display):
        return
    found = interruptions_of(ctx.policy, screen, ctx.info.locale)
    if all(interruption.window != active.id for interruption in found):
        return
    try:
        snapshot = capture(ctx, screen)
    except Refusal:
        return
    kinds = ", ".join(dict.fromkeys(note.kind.value for note in snapshot.interruptions))
    raise Refusal(
        ErrorCode.INTERRUPTED,
        f"A pop-up is in the way of the target ({kinds}). Nothing was sent, and agent-phone does not "
        f"dismiss it. Snapshot {snapshot.id} shows it.",
        {"snapshot": snapshot.id, "interruptions": snapshot.interruption_data()},
    )
