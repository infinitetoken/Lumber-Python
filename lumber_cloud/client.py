from __future__ import annotations

import atexit
import base64
import binascii
import enum
import os
import socket
import sys
import threading
import time
import traceback
import weakref
from collections.abc import Mapping
from types import TracebackType
from typing import Any, Optional, Union

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from . import _crypto
from ._contract import DEFAULT_ENDPOINT, KEY_BYTES, build_payload, split_api_key
from ._delivery import Sender, Transport, warn
from ._version import __version__

ExcInfo = Union[
    bool,
    BaseException,
    tuple[type[BaseException], BaseException, Optional[TracebackType]],
    tuple[None, None, None],
    None,
]


class LogLevel(enum.IntEnum):
    """Lumber's log levels. The numbers are the API's: never change them."""

    DEBUG = 0
    INFO = 1
    WARN = 2
    ERROR = 3
    FATAL = 4


class LumberClient:
    """Encrypts logs with the app's key and sends them to Lumber from a background thread.

    Every log method returns at once and never raises. Logs still queued when the program exits get up to
    `shutdown_timeout` seconds to send; call flush() to wait for them yourself.
    """

    def __init__(
        self,
        api_key: str,
        *,
        endpoint: str = DEFAULT_ENDPOINT,
        environment: str | None = None,
        auto_context: bool = True,
        caller: bool = False,
        caller_depth: int = 0,
        timeout: float = 10.0,
        max_queue: int = 10_000,
        shutdown_timeout: float = 5.0,
    ) -> None:
        """
        api_key: the API key from the app's Secrets screen in Lumber, `<token>.<encryptionKey>`. Only the token is sent
            to Lumber; the encryption key encrypts every log and never leaves this process.
        endpoint: the Lumber API's URL, for testing against another server.
        environment: sent with every log as `env` in its context ("production", "staging").
        auto_context: send the process id and hostname (and `environment`) with every log, in its context.
        caller: also send the file, line and function that logged.
        caller_depth: stack frames to skip for `caller`, one for each wrapper around this client.
        timeout: seconds to wait for Lumber to answer one log.
        max_queue: logs waiting to send before new ones are dropped, while Lumber can't be reached.
        shutdown_timeout: seconds queued logs get to send when the program exits.
        """
        token, encryption_key = split_api_key(api_key or "")
        if not token:
            raise ValueError("[lumber] Missing api_key. Create one on your app's Secrets screen in Lumber.")
        if not encryption_key:
            raise ValueError(
                "[lumber] api_key has no encryption key. Copy a new API key from your app's Secrets screen in Lumber, "
                "which includes it."
            )
        try:
            key = base64.b64decode(encryption_key, validate=True)
        except (binascii.Error, ValueError):
            key = b""
        if len(key) != KEY_BYTES:
            raise ValueError(
                f"[lumber] api_key's encryption key should be {KEY_BYTES} bytes of base64, got {len(key)}. Copy the "
                "API key again from your app's Secrets screen in Lumber."
            )

        self._aead = AESGCM(key)
        self._environment = environment
        self._auto_context = auto_context
        self._caller = caller
        self._caller_depth = caller_depth
        self._hostname = _hostname() if auto_context else None
        self.shutdown_timeout = shutdown_timeout
        user_agent = f"lumber-cloud-python/{__version__} python/{sys.version_info[0]}.{sys.version_info[1]}"
        self._sender = Sender(lambda: Transport(endpoint, token, user_agent, timeout), max_queue)
        _live_clients.add(self)

    # --- Logging ---

    def debug(self, message: Any, /, **data: Any) -> None:
        """Logs at DEBUG. Keyword arguments are the log's data: `request_id`, `trace_id`, `context`, `metadata`,
        `exc_info`, and any others, which go into its metadata."""
        self._log(LogLevel.DEBUG, message, data)

    def info(self, message: Any, /, **data: Any) -> None:
        """Logs at INFO. See debug() for the keyword arguments."""
        self._log(LogLevel.INFO, message, data)

    def warn(self, message: Any, /, **data: Any) -> None:
        """Logs at WARN. See debug() for the keyword arguments."""
        self._log(LogLevel.WARN, message, data)

    warning = warn

    def error(self, message: Any, /, **data: Any) -> None:
        """Logs at ERROR. See debug() for the keyword arguments."""
        self._log(LogLevel.ERROR, message, data)

    def exception(self, message: Any, /, **data: Any) -> None:
        """Logs at ERROR with the exception being handled, for use in an `except` block."""
        data.setdefault("exc_info", True)
        self._log(LogLevel.ERROR, message, data)

    def fatal(self, message: Any, /, **data: Any) -> None:
        """Logs at FATAL. See debug() for the keyword arguments."""
        self._log(LogLevel.FATAL, message, data)

    critical = fatal

    def flush(self, timeout: float | None = None) -> bool:
        """Waits until every queued log is sent (or dropped). False when `timeout` seconds ran out first."""
        return self._sender.flush(timeout)

    def close(self, timeout: float | None = None) -> bool:
        """Sends what's queued, waiting up to `timeout` seconds, and stops. Logs after this are dropped."""
        _live_clients.discard(self)
        return self._sender.close(timeout)

    def __enter__(self) -> LumberClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close(self.shutdown_timeout)

    # --- Internals ---

    def _log(self, level: LogLevel, message: Any, data: dict[str, Any]) -> None:
        # Called straight from a log method, here or the module's, so the caller is always three frames up
        try:
            exc_info = data.pop("exc_info", None)
            context = self._caller_context() if self._caller else None
            self._send(level, message, data, exc_info, context)
        except Exception as err:
            warn(f"couldn't log {message!r}: {err!r}")

    def _send(
        self,
        level: int,
        message: Any,
        data: Mapping[str, Any],
        exc_info: ExcInfo = None,
        context: Mapping[str, Any] | None = None,
    ) -> None:
        """Builds, encrypts and queues one log. `data` takes Python's names (`request_id`, `trace_id`) or the API's;
        `context` goes over the automatic context, under the log's own."""
        fields = dict(data)
        for name, wire in (("request_id", "requestId"), ("trace_id", "traceId")):
            if name in fields:
                value = fields.pop(name)
                if value is not None:
                    fields.setdefault(wire, value)
        error = _exception(exc_info)
        if error:
            for key, value in error.items():
                fields.setdefault(key, value)

        auto: dict[str, Any] = {}
        if self._auto_context:
            auto["pid"] = os.getpid()
            if self._hostname:
                auto["hostname"] = self._hostname
            if self._environment:
                auto["env"] = self._environment
        if context:
            auto.update(context)

        payload = build_payload(int(level), message if isinstance(message, str) else str(message), fields, auto)
        self._sender.enqueue(_crypto.to_json({"level": int(level), "encrypted": _crypto.encrypt(self._aead, payload)}))

    def _caller_context(self) -> dict[str, Any] | None:
        try:
            frame = sys._getframe(3 + self._caller_depth)
        except ValueError:
            return None
        return {"code": frame.f_code.co_filename, "line": frame.f_lineno, "method": frame.f_code.co_name}


def _hostname() -> str | None:
    try:
        return socket.gethostname() or None
    except OSError:
        return None


def _exception(exc_info: ExcInfo) -> dict[str, str] | None:
    """An exception as two metadata keys: `exception`, its type and message on one line, and `traceback`."""
    if not exc_info:
        return None
    if isinstance(exc_info, BaseException):
        info: tuple[Any, Any, Any] = (type(exc_info), exc_info, exc_info.__traceback__)
    elif isinstance(exc_info, tuple):
        info = exc_info
    else:
        info = sys.exc_info()
    if info[1] is None:
        return None
    return {
        "exception": "".join(traceback.format_exception_only(info[0], info[1])).strip(),
        "traceback": "".join(traceback.format_exception(*info)).rstrip(),
    }


# Every client sends what it has queued when the program exits, sharing one deadline
_live_clients: weakref.WeakSet[LumberClient] = weakref.WeakSet()
_exit_lock = threading.Lock()


@atexit.register
def _flush_at_exit() -> None:
    with _exit_lock:
        clients = list(_live_clients)
        if not clients:
            return
        deadline = time.monotonic() + max(client.shutdown_timeout for client in clients)
        for client in clients:
            if not client.flush(max(0.0, deadline - time.monotonic())):
                warn("exiting with logs still waiting to send")
                return
