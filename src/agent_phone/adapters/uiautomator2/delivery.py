"""How far an input got, as a `Delivery`. The write-side table; reads never consult it.

| what happened                                               | Delivery                          |
|-------------------------------------------------------------|-----------------------------------|
| forward missing, connection refused, before any byte sent   | NotSent(SERVER_UNAVAILABLE)       |
| request written, timeout or reset before an answer          | Sent(UNACKNOWLEDGED)              |
| answered `UiObjectNotFoundException` (selector-based calls) | NotSent(STALE_REF)                |
| answered `UiAutomation not connected`, `DeadObjectException`| NotSent(SERVER_UNAVAILABLE) *     |
| answered with any other error                               | Sent(UNACKNOWLEDGED)              |
| answered with a result                                      | Sent(ACKNOWLEDGED)                |
| adb shell input (launch, stop, open-uri) exited non-zero    | Sent(UNACKNOWLEDGED)              |

`*` inferred from the server failing before it reached UiAutomation; unit 4 confirms it on
the device. An unclassified error lands on the unsafe side, so a code nobody has seen yet
can never authorize a retry.
"""

from __future__ import annotations

from agent_phone.adapters.uiautomator2.rpc import RpcResult
from agent_phone.core.phone import Delivery


def classify(result: RpcResult) -> Delivery:
    raise NotImplementedError


def classify_shell(exit_status: int | None, written: bool) -> Delivery:
    raise NotImplementedError
