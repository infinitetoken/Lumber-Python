from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any

import pytest
from conftest import API_KEY, decrypt

from lumber_cloud import LogLevel, LumberClient, LumberHandler, lumber_level


@pytest.fixture
def logger(transport: Any) -> Iterator[logging.Logger]:
    logger = logging.getLogger("tests.handler")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    handler = LumberHandler(API_KEY, auto_context=False)
    logger.addHandler(handler)
    yield logger
    logger.removeHandler(handler)


def logs(transport: Any, logger: logging.Logger) -> list[dict[str, Any]]:
    for handler in logger.handlers:
        handler.flush()
    return [decrypt(body) for body in transport.instances[0].bodies]


@pytest.mark.parametrize(
    ("levelno", "level"),
    [
        (5, LogLevel.DEBUG),
        (logging.DEBUG, LogLevel.DEBUG),
        (logging.INFO, LogLevel.INFO),
        (25, LogLevel.INFO),
        (logging.WARNING, LogLevel.WARN),
        (logging.ERROR, LogLevel.ERROR),
        (logging.CRITICAL, LogLevel.FATAL),
        (60, LogLevel.FATAL),
    ],
)
def test_levels(levelno: int, level: LogLevel) -> None:
    assert lumber_level(levelno) == level


def test_a_record(transport: Any, logger: logging.Logger) -> None:
    logger.warning("Rate limit at %d%%", 90, extra={"request_id": "req-1", "user_id": 7, "context": {"region": "us"}})
    (log,) = logs(transport, logger)
    assert log["level"] == 2
    assert log["message"] == "Rate limit at 90%"
    assert log["requestId"] == "req-1"
    assert log["metadata"] == {"user_id": 7}
    assert log["context"]["logger"] == "tests.handler"
    assert log["context"]["code"] == __file__
    assert log["context"]["method"] == "test_a_record"
    assert isinstance(log["context"]["line"], int)
    assert log["context"]["region"] == "us"


def test_an_exception(transport: Any, logger: logging.Logger) -> None:
    try:
        1 / 0  # noqa: B018
    except ZeroDivisionError:
        logger.exception("Report failed")
    (log,) = logs(transport, logger)
    assert log["level"] == 3
    assert log["message"] == "Report failed"
    assert log["metadata"]["exception"] == "ZeroDivisionError: division by zero"
    assert "Traceback (most recent call last):" in log["metadata"]["traceback"]


def test_the_handler_level(transport: Any, logger: logging.Logger) -> None:
    logger.handlers[0].setLevel(logging.WARNING)
    logger.info("skipped")
    logger.error("sent")
    assert [log["message"] for log in logs(transport, logger)] == ["sent"]


def test_sharing_a_client(transport: Any) -> None:
    client = LumberClient(API_KEY)
    assert LumberHandler(client=client).client is client
    with pytest.raises(ValueError, match="not both"):
        LumberHandler(API_KEY, client=client)
    with pytest.raises(ValueError, match="api_key or a client"):
        LumberHandler()
