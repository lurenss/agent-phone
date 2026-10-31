"""JSON-RPC to the u2.jar server through an adb port forward, sent exactly once.

The uiautomator2 Python package is not imported at runtime: its import cost lands on every CLI
call, and its calls retry on their own (`@retry` on `_do_dump_hierarchy`, server restarts on
connection errors). This client speaks `POST /jsonrpc/0` with `http.client` and records how far
each request got, which is what `delivery.py` needs to tell NotSent from Sent.
"""

from __future__ import annotations

import http.client
import json
from dataclasses import dataclass
from enum import Enum

ERROR_CHARS = 600


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
        again by their caller; input methods are called once by `phone.U2Phone.inject`.

        A request counts as written from the moment the connection is up. Through an adb
        forward a connection can be accepted on the computer while the phone refuses it, so a
        dead server shows as `WRITTEN`, which is the safe side for input.
        """
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
        connection = http.client.HTTPConnection("127.0.0.1", self._port, timeout=self._timeout)
        try:
            try:
                connection.connect()
            except OSError:
                return RpcResult(Phase.NOT_CONNECTED, None, None)
            try:
                connection.request("POST", "/jsonrpc/0", body, {"Content-Type": "application/json"})
                reply = connection.getresponse()
                content = reply.read()
            except (OSError, http.client.HTTPException):
                return RpcResult(Phase.WRITTEN, None, None)
            return answer(reply.status, reply.reason, content)
        finally:
            connection.close()

    def ping(self, timeout_s: float = 1.0) -> bool:
        connection = http.client.HTTPConnection("127.0.0.1", self._port, timeout=timeout_s)
        try:
            connection.request("GET", "/ping")
            return connection.getresponse().status == 200
        except (OSError, http.client.HTTPException):
            return False
        finally:
            connection.close()


def answer(status: int, reason: str, content: bytes) -> RpcResult:
    if status != 200:
        return RpcResult(Phase.ANSWERED, None, f"HTTP {status} {reason}")
    try:
        document = json.loads(content)
    except ValueError:
        return RpcResult(
            Phase.ANSWERED, None, f"The server answered with text that is not JSON: {content[:80]!r}"
        )
    if not isinstance(document, dict):
        return RpcResult(Phase.ANSWERED, None, "The server answered with JSON that is not an object.")
    if "error" in document:
        return RpcResult(Phase.ANSWERED, None, json.dumps(document["error"])[:ERROR_CHARS])
    return RpcResult(Phase.ANSWERED, document.get("result"), None)
