from __future__ import annotations

import http.server
import json
import threading
from collections.abc import Iterator
from typing import Any

import pytest
from conftest import API_KEY, decrypt

from lumber_cloud import LumberClient
from lumber_cloud._delivery import Answer, Transport


def messages(fake: Any) -> list[str]:
    return [decrypt(body)["message"] for body in fake.bodies]


def test_a_refused_log_is_dropped_at_once(transport: Any, warnings: list[str]) -> None:
    client = LumberClient(API_KEY)
    fake = transport.instances[0]
    fake.answers = [Answer(401, body=b'{"message":"Invalid API key"}')]
    client.info("refused")
    client.info("next")
    assert client.flush(5)
    assert messages(fake) == ["refused", "next"]
    assert warnings == ["log refused: HTTP 401 (Invalid API key)"]


def test_a_failure_is_tried_again(transport: Any, warnings: list[str]) -> None:
    client = LumberClient(API_KEY)
    fake = transport.instances[0]
    fake.answers = [Answer(503), Answer(None, error=ConnectionRefusedError("down")), Answer(201)]
    client.info("flaky")
    client.info("next")
    assert client.flush(5)
    assert messages(fake) == ["flaky", "flaky", "flaky", "next"]
    assert warnings == ["send failed: HTTP 503", "send error: ConnectionRefusedError('down')"]


def test_a_log_is_dropped_after_five_failures(transport: Any, warnings: list[str]) -> None:
    client = LumberClient(API_KEY)
    fake = transport.instances[0]
    fake.answers = [Answer(500)] * 5
    client.info("doomed")
    client.info("next")
    assert client.flush(5)
    assert messages(fake) == ["doomed"] * 5 + ["next"]
    assert warnings[-1] == "dropping log after 5 failed attempts"


def test_the_monthly_cap_pauses_sending(transport: Any, warnings: list[str]) -> None:
    client = LumberClient(API_KEY)
    fake = transport.instances[0]
    fake.block.clear()
    fake.answers = [
        Answer(429, retry_after="86400", body=b'{"message":"This team has sent its 10,000 logs for the month."}')
    ]
    client.info("capped")
    client.info("queued behind it")
    fake.block.set()
    assert client.flush(5)
    client.info("during the pause")
    assert client.flush(5)
    assert messages(fake) == ["capped"]
    assert len(warnings) == 1
    assert warnings[0].startswith("This team has sent its 10,000 logs for the month. Dropping logs until ")

    client._sender._paused_until = 0
    client.info("next month")
    assert client.flush(5)
    assert messages(fake) == ["capped", "next month"]


def test_a_pause_without_retry_after_lasts_an_hour(transport: Any, warnings: list[str]) -> None:
    client = LumberClient(API_KEY)
    transport.instances[0].answers = [Answer(429)]
    client.info("capped")
    assert client.flush(5)
    import time

    assert 3590 < client._sender._paused_until - time.monotonic() <= 3600
    assert warnings[0].startswith("Lumber is refusing logs for now (HTTP 429). Dropping logs until ")


def test_flush_gives_up_at_its_timeout(transport: Any) -> None:
    client = LumberClient(API_KEY)
    transport.instances[0].block.clear()
    client.info("stuck")
    assert client.flush(0.05) is False
    transport.instances[0].block.set()
    assert client.flush(5) is True


def test_a_full_queue_drops_new_logs(transport: Any, warnings: list[str]) -> None:
    client = LumberClient(API_KEY, max_queue=1)
    transport.instances[0].block.clear()
    for i in range(10):
        client.info(f"log {i}")
    transport.instances[0].block.set()
    assert client.flush(5)
    assert len(transport.instances[0].bodies) < 10
    assert warnings == ["dropping logs: 1 are already waiting to send"]


# --- The real connection, against a server on this machine ---


class Recorder(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    requests: list[dict[str, Any]] = []
    connections: set[tuple[str, int]] = set()
    close_next = False
    status = 201

    def do_POST(self) -> None:
        body = self.rfile.read(int(self.headers["Content-Length"]))
        Recorder.requests.append({"path": self.path, "headers": dict(self.headers), "body": json.loads(body)})
        Recorder.connections.add(self.client_address)
        reply = b'{"data":{}}'
        self.send_response(Recorder.status)
        if Recorder.status == 429:
            self.send_header("Retry-After", "120")
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(reply)))
        self.end_headers()
        self.wfile.write(reply)
        if Recorder.close_next:
            Recorder.close_next = False
            self.close_connection = True

    def log_message(self, *args: Any) -> None:
        pass


@pytest.fixture
def server() -> Iterator[str]:
    Recorder.requests, Recorder.connections, Recorder.close_next, Recorder.status = [], set(), False, 201
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Recorder)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}/v1"
    httpd.shutdown()
    httpd.server_close()


def test_the_connection_is_kept_open(server: str) -> None:
    transport = Transport(server, "token", "test", 5)
    for _ in range(3):
        assert transport.post(b'{"level":1}').status == 201
    assert len(Recorder.connections) == 1
    request = Recorder.requests[0]
    assert request["path"] == "/v1/logs"
    assert request["headers"]["Authorization"] == "Bearer token"
    assert request["headers"]["Content-Type"] == "application/json"
    transport.close()


def test_a_closed_connection_is_opened_again(server: str) -> None:
    transport = Transport(server, "token", "test", 5)
    Recorder.close_next = True
    assert transport.post(b"{}").status == 201
    assert transport.post(b"{}").status == 201
    assert len(Recorder.connections) == 2
    assert len(Recorder.requests) == 2
    transport.close()


def test_retry_after_is_read(server: str) -> None:
    Recorder.status = 429
    answer = Transport(server, "token", "test", 5).post(b"{}")
    assert (answer.status, answer.retry_after) == (429, "120")


def test_no_server(server: str) -> None:
    answer = Transport("http://127.0.0.1:9", "token", "test", 1).post(b"{}")
    assert answer.status is None and isinstance(answer.error, OSError)


def test_a_bad_endpoint() -> None:
    with pytest.raises(ValueError, match="endpoint"):
        Transport("api.lumber.example", "token", "test", 5)


def test_end_to_end(server: str) -> None:
    client = LumberClient(API_KEY, endpoint=server, auto_context=False)
    client.error("Payment failed", request_id="req-1", order_id=789)
    assert client.flush(5)
    (request,) = Recorder.requests
    assert request["headers"]["Authorization"] == f"Bearer {API_KEY.split('.')[0]}"
    assert decrypt(request["body"]) == {
        "level": 3,
        "message": "Payment failed",
        "requestId": "req-1",
        "metadata": {"order_id": 789},
    }
    client.close()
