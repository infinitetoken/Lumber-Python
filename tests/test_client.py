from __future__ import annotations

import base64
import datetime
import math
import os
import socket
import time
from typing import Any

import pytest
from conftest import API_KEY, KEY, decrypt

import lumber_cloud
from lumber_cloud import LogLevel, LumberClient, _delivery

TOKEN = API_KEY.split(".")[0]


def sent(transport: Any, client: LumberClient) -> list[dict[str, Any]]:
    assert client.flush(5)
    return [decrypt(body) for instance in transport.instances for body in instance.bodies]


@pytest.mark.parametrize(
    ("api_key", "error"),
    [
        ("", "Missing api_key"),
        ("   ", "Missing api_key"),
        (TOKEN, "no encryption key"),
        (f"{TOKEN}.", "no encryption key"),
        (f"{TOKEN}.{base64.b64encode(os.urandom(16)).decode()}", "32 bytes"),
        (f"{TOKEN}.not base64!", "32 bytes"),
    ],
)
def test_refuses_a_bad_api_key(api_key: str, error: str) -> None:
    with pytest.raises(ValueError, match=error):
        LumberClient(api_key)


def test_sends_only_the_token(transport: Any) -> None:
    client = LumberClient(f"  {API_KEY}\n")
    client.info("hello")
    assert client.flush(5)
    fake = transport.instances[0]
    assert fake.token == TOKEN
    assert KEY not in str(fake.bodies) and "hello" not in str(fake.bodies)
    assert fake.user_agent.startswith(f"lumber-cloud-python/{lumber_cloud.__version__} ")


def test_logging_never_waits_for_the_network(transport: Any) -> None:
    client = LumberClient(API_KEY)
    client.info("first")
    transport.instances[0].block.clear()
    started = time.monotonic()
    for i in range(1000):
        client.info(f"log {i}")
    elapsed = time.monotonic() - started
    transport.instances[0].block.set()
    assert elapsed < 1.0
    assert len(sent(transport, client)) == 1001


def test_levels(transport: Any) -> None:
    client = LumberClient(API_KEY, auto_context=False)
    client.debug("d")
    client.info("i")
    client.warn("w")
    client.warning("w2")
    client.error("e")
    client.fatal("f")
    client.critical("c")
    assert [(log["level"], log["message"]) for log in sent(transport, client)] == [
        (0, "d"),
        (1, "i"),
        (2, "w"),
        (2, "w2"),
        (3, "e"),
        (4, "f"),
        (4, "c"),
    ]
    assert transport.instances[0].bodies[0]["level"] == LogLevel.DEBUG


def test_python_names_for_the_ids(transport: Any) -> None:
    client = LumberClient(API_KEY, auto_context=False)
    client.info("ids", request_id="req-1", trace_id="trace-1", user_id=7)
    client.info("none", request_id=None)
    first, second = sent(transport, client)
    assert first == {
        "level": 1,
        "message": "ids",
        "requestId": "req-1",
        "traceId": "trace-1",
        "metadata": {"user_id": 7},
    }
    assert second == {"level": 1, "message": "none"}


def test_automatic_context(transport: Any) -> None:
    client = LumberClient(API_KEY, environment="production")
    client.info("hello", context={"region": "us"})
    (log,) = sent(transport, client)
    assert log["context"] == {"pid": os.getpid(), "hostname": socket.gethostname(), "env": "production", "region": "us"}


def test_no_automatic_context(transport: Any) -> None:
    client = LumberClient(API_KEY, auto_context=False, environment="production")
    client.info("hello")
    assert sent(transport, client) == [{"level": 1, "message": "hello"}]


def test_caller(transport: Any) -> None:
    client = LumberClient(API_KEY, auto_context=False, caller=True)

    def wrapper(message: str) -> None:
        client.info(message)

    client.info("direct")
    client.exception("not in an except block")
    wrapper("wrapped")
    direct, exception, wrapped = sent(transport, client)
    assert direct["context"]["code"] == __file__
    assert direct["context"]["method"] == "test_caller"
    assert direct["context"]["line"] > test_caller.__code__.co_firstlineno
    assert exception["context"]["method"] == "test_caller"
    assert wrapped["context"]["method"] == "wrapper"

    deeper = LumberClient(API_KEY, auto_context=False, caller=True, caller_depth=1)

    def logs_for_me(message: str) -> None:
        deeper.info(message)

    logs_for_me("skips the wrapper")
    assert sent(transport, deeper)[-1]["context"]["method"] == "test_caller"


def test_caller_through_the_module(transport: Any) -> None:
    lumber_cloud.config(API_KEY, auto_context=False, caller=True)
    lumber_cloud.warn("from the module")
    lumber_cloud.flush(5)
    (log,) = [decrypt(body) for body in transport.instances[0].bodies]
    assert log["context"]["method"] == "test_caller_through_the_module"


def test_exceptions(transport: Any) -> None:
    client = LumberClient(API_KEY, auto_context=False)
    try:
        raise ValueError("bad amount")
    except ValueError as err:
        client.exception("Payment failed", order_id=7)
        caught = err
    client.warn("later", exc_info=caught)
    client.error("no exception", exc_info=True)
    handled, later, none = sent(transport, client)
    assert handled["level"] == 3
    assert handled["message"] == "Payment failed"
    assert handled["metadata"]["order_id"] == 7
    assert handled["metadata"]["exception"] == "ValueError: bad amount"
    assert handled["metadata"]["traceback"].startswith("Traceback (most recent call last):")
    assert handled["metadata"]["traceback"].endswith("ValueError: bad amount")
    assert later["metadata"]["exception"] == "ValueError: bad amount"
    assert none == {"level": 3, "message": "no exception"}


def test_values_json_has_no_type_for(transport: Any) -> None:
    client = LumberClient(API_KEY, auto_context=False)
    when = datetime.datetime(2026, 11, 2, 9, 30, tzinfo=datetime.timezone.utc)
    loop: dict[str, Any] = {"name": "loop"}
    loop["self"] = loop
    client.info("types", when=when, tags={"a"}, raw=b"bytes", obj=object, ratio=math.nan, ok=1.5)
    client.info("cycle", loop=loop)
    client.info(42)
    types, cycle, number = sent(transport, client)
    assert types["metadata"] == {
        "when": "2026-11-02T09:30:00+00:00",
        "tags": ["a"],
        "raw": "bytes",
        "obj": "<class 'object'>",
        "ratio": None,
        "ok": 1.5,
    }
    assert cycle["metadata"]["loop"] == {"name": "loop", "self": "[Circular]"}
    assert number["message"] == "42"


def test_the_module_needs_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lumber_cloud, "_client", None)
    with pytest.raises(RuntimeError, match="config"):
        lumber_cloud.info("too early")


def test_the_module(transport: Any) -> None:
    client = lumber_cloud.config(API_KEY, auto_context=False)
    lumber_cloud.debug("d")
    lumber_cloud.info("i", port=8000)
    lumber_cloud.warning("w")
    lumber_cloud.error("e")
    lumber_cloud.critical("c")
    try:
        raise KeyError("missing")
    except KeyError:
        lumber_cloud.exception("x")
    assert lumber_cloud.flush(5)
    logs = [decrypt(body) for body in transport.instances[0].bodies]
    assert [log["level"] for log in logs] == [0, 1, 2, 3, 4, 3]
    assert logs[1]["metadata"] == {"port": 8000}
    assert logs[5]["metadata"]["exception"] == "KeyError: 'missing'"
    assert client is lumber_cloud._client


def test_a_forked_child_starts_over(transport: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    client = LumberClient(API_KEY, auto_context=False)
    parent = transport.instances[0]
    parent.block.clear()
    client.info("parent")
    client.info("parent, still queued")
    monkeypatch.setattr(_delivery.os, "getpid", lambda: -1)
    client.info("child")
    assert client.flush(5)
    child = transport.instances[1]
    assert [decrypt(body)["message"] for body in child.bodies] == ["child"]
    parent.block.set()


def test_close(transport: Any) -> None:
    with LumberClient(API_KEY, auto_context=False) as client:
        client.info("before")
    client.info("after")
    assert [decrypt(body)["message"] for body in transport.instances[0].bodies] == ["before"]
    assert transport.instances[0].closed
