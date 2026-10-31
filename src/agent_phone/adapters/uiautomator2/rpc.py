"""JSON-RPC to the u2.jar server through an adb port forward, sent exactly once.

The uiautomator2 Python package is not imported at runtime: its import cost lands on every CLI
call, and its calls retry on their own (`@retry` on `_do_dump_hierarchy`, server restarts on
connection errors). This client speaks `POST /jsonrpc/0` with `http.client` and records how far
each request got, which is what `delivery.py` needs to tell NotSent from Sent.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Phase(Enum):
    NOT_CONNECTED = "not_connected"
    WRITTEN = "written"
    ANSWERED = "answered"


@dataclass(frozen=True, slots=True)
class RpcResult:
    """`error_message` holds the server's exception text when `answered` with an error."""

    phase: Phase
    result: object | None
    error_message: str | None


class JsonRpc:
    def __init__(self, host_port: int, timeout_s: float) -> None:
        self._port = host_port
        self._timeout = timeout_s

    def call(self, method: str, params: list[object]) -> RpcResult:
        """Never raises for transport trouble and never retries. Read methods may be called
        again by their caller; input methods are called once by `phone.U2Phone.inject`."""
        raise NotImplementedError
