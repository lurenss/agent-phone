"""How far an input got, as a `Delivery`. The write-side table; reads never consult it.

| what happened                                               | Delivery                          |
|-------------------------------------------------------------|-----------------------------------|
| forward missing, connection refused, before any byte sent   | NotSent(SERVER_UNAVAILABLE)       |
| request written, timeout or reset before an answer          | Sent(UNACKNOWLEDGED)              |
| answered `UiObjectNotFoundException` (selector-based calls) | NotSent(STALE_REF)                |
| answered with any other error                               | Sent(UNACKNOWLEDGED)              |
| answered with a result                                      | Sent(ACKNOWLEDGED)                |
| adb shell (launch, stop, open-uri, rotate) printed an error | NotSent(NOT_FOUND)                |
| adb shell exited non-zero, or did not finish                | Sent(UNACKNOWLEDGED)              |
| adb shell exited 0                                          | Sent(ACKNOWLEDGED)                |

`am start` echoes the intent it starts, with its link in it, before it prints a result. A line of
that echo that starts with "Error:" would read as proof that nothing started, so no word of an
adb shell command may break a line (`shell.Shell.run`, `phone.intent_of`), and the echo cannot
hold a line of the caller's making. The clipboard is a call to the server, not a shell command,
and `classify` reads only an error message, never the text a call returned or was given.

`UiAutomation not connected` and `DeadObjectException` stay on the unsafe side. The sketch
guessed that the server fails before it reaches UiAutomation, but a click is a touch down and a
touch up (A2-11), and nothing shows that a connection lost between the two sent neither. An
unclassified error lands on the unsafe side too, so a code nobody has seen yet can never
authorize a retry.
"""

from __future__ import annotations

from agent_phone.adapters.uiautomator2.rpc import Phase, RpcResult
from agent_phone.core.outcome import ErrorCode
from agent_phone.core.phone import Ack, Delivery, NotSent, Sent

NOT_FOUND_ERROR = "UiObjectNotFoundException"
NOTHING_STARTED = ("Error:", "No activities found to run")
"""What `am start` and `monkey` print when no activity matches, so nothing was started."""


def classify(result: RpcResult) -> Delivery:
    match result.phase:
        case Phase.NOT_CONNECTED:
            return NotSent(
                ErrorCode.SERVER_UNAVAILABLE, "The server did not take the connection. Nothing was sent."
            )
        case Phase.WRITTEN:
            return Sent(Ack.UNACKNOWLEDGED, "The request was written and no answer came back.")
    if result.error_message is None:
        return Sent(Ack.ACKNOWLEDGED, f"The server answered {result.result!r}.")
    if NOT_FOUND_ERROR in result.error_message:
        return NotSent(
            ErrorCode.STALE_REF, "The server found no element for the selector. Nothing was changed."
        )
    return Sent(Ack.UNACKNOWLEDGED, f"The server answered with an error: {result.error_message[:200]}")


def classify_shell(exit_status: int | None, written: bool, output: str = "") -> Delivery:
    """`written` is False when adb never started. `exit_status` None means it did not finish."""
    if not written:
        return NotSent(ErrorCode.TRANSPORT, "adb did not start. Nothing was sent.")
    lines = (line.strip(" *") for line in output.splitlines())
    said = next((line for line in lines if line.startswith(NOTHING_STARTED)), None)
    if said is not None:
        return NotSent(ErrorCode.NOT_FOUND, f"Nothing was started: {said[:200]}")
    if exit_status == 0:
        return Sent(Ack.ACKNOWLEDGED, "adb shell exited 0.")
    if exit_status is None:
        return Sent(Ack.UNACKNOWLEDGED, "adb shell did not finish in time.")
    return Sent(Ack.UNACKNOWLEDGED, f"adb shell exited {exit_status}.")
