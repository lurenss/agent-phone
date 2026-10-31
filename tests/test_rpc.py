import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from agent_phone.adapters.uiautomator2.rpc import JsonRpc, Phase


class Handler(BaseHTTPRequestHandler):
    seen: list = []

    def log_message(self, *args):
        pass

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Length", "4")
        self.end_headers()
        self.wfile.write(b"pong")

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.seen.append(body)
        method = body["method"]
        if method == "drop":
            self.connection.close()
            return
        if method == "http500":
            self.send_response(500)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        reply = (
            {"error": {"code": -32000, "message": "UiAutomation not connected"}}
            if method == "fail"
            else {"result": f"<{method}>"}
        )
        data = json.dumps(reply).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


@pytest.fixture
def port():
    Handler.seen = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
    yield server.server_address[1]
    server.shutdown()
    server.server_close()


@pytest.fixture
def closed_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def test_an_answered_call_returns_its_result_and_sends_one_request(port):
    result = JsonRpc(port, 2).call("dumpWindowHierarchy", [False, 50])
    assert (result.phase, result.result, result.error_message) == (
        Phase.ANSWERED,
        "<dumpWindowHierarchy>",
        None,
    )
    assert [call["params"] for call in Handler.seen] == [[False, 50]]


def test_a_server_error_is_answered_with_its_text(port):
    result = JsonRpc(port, 2).call("fail", [])
    assert result.phase is Phase.ANSWERED and "UiAutomation not connected" in result.error_message


def test_an_http_error_is_answered_with_its_status(port):
    result = JsonRpc(port, 2).call("http500", [])
    assert result.phase is Phase.ANSWERED and "500" in result.error_message


def test_a_connection_the_server_drops_after_the_request_counts_as_written_and_is_not_retried(port):
    result = JsonRpc(port, 2).call("drop", [])
    assert result.phase is Phase.WRITTEN
    assert len(Handler.seen) == 1


def test_a_closed_port_is_not_connected(closed_port):
    assert JsonRpc(closed_port, 2).call("anything", []).phase is Phase.NOT_CONNECTED


def test_ping_is_true_for_a_server_and_false_for_nothing(port, closed_port):
    assert JsonRpc(port, 2).ping() is True
    assert JsonRpc(closed_port, 2).ping() is False
