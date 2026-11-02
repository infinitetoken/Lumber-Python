from __future__ import annotations

import logging
from typing import Any

from ._delivery import warn
from .client import LogLevel, LumberClient

# Every attribute logging puts on a record itself. Anything else came from `extra=` and goes into the log's metadata.
_RECORD_ATTRIBUTES = frozenset(vars(logging.LogRecord("", 0, "", 0, "", (), None))) | {"message", "asctime", "taskName"}


def lumber_level(levelno: int) -> LogLevel:
    """A `logging` level as Lumber's: CRITICAL is FATAL, and a custom level counts as the standard one below it."""
    if levelno >= logging.CRITICAL:
        return LogLevel.FATAL
    if levelno >= logging.ERROR:
        return LogLevel.ERROR
    if levelno >= logging.WARNING:
        return LogLevel.WARN
    if levelno >= logging.INFO:
        return LogLevel.INFO
    return LogLevel.DEBUG


class LumberHandler(logging.Handler):
    """Sends `logging` records to Lumber.

    The message is the record's message with its arguments filled in (formatters aren't used, since a log's fields are
    sent apart). `extra=` keys go into the log's metadata, except `request_id` and `trace_id`, which are the log's own
    fields, and `context`, which goes into its context with the logger, file, line and function. An exception
    (`logger.exception()`, `exc_info=True`) goes into metadata as `exception` and `traceback`.

    Pass `api_key=` and any of LumberClient's options, or a `client=` to share one.
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        level: int = logging.NOTSET,
        client: LumberClient | None = None,
        **options: Any,
    ) -> None:
        super().__init__(level)
        if client is None:
            if api_key is None:
                raise ValueError("[lumber] LumberHandler needs an api_key or a client.")
            client = LumberClient(api_key, **options)
        elif api_key is not None or options:
            raise ValueError("[lumber] Pass LumberHandler an api_key and options, or a client, not both.")
        self.client = client

    def emit(self, record: logging.LogRecord) -> None:
        try:
            data = {
                key: value
                for key, value in vars(record).items()
                if key not in _RECORD_ATTRIBUTES and not key.startswith("_")
            }
            context = {"logger": record.name, "code": record.pathname, "line": record.lineno, "method": record.funcName}
            self.client._send(lumber_level(record.levelno), record.getMessage(), data, record.exc_info, context)
        except Exception as err:
            warn(f"couldn't send a log record: {err!r}")

    def flush(self) -> None:
        self.client.flush(self.client.shutdown_timeout)

    def close(self) -> None:
        # logging.shutdown() closes handlers at exit: send what's queued, but leave a shared client running
        self.flush()
        super().close()
