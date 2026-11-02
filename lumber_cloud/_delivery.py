"""Sends logs to POST /logs from one background thread, in the order they were logged, over a connection kept open
between logs. What each answer means and how long to wait are Lumber-Kit's (see _contract)."""

from __future__ import annotations

import datetime
import http.client
import json
import os
import queue
import ssl
import sys
import threading
import time
import urllib.parse
from dataclasses import dataclass
from typing import Callable

from ._contract import INGEST_PATH, MAX_ATTEMPTS, PAUSE, delivery_outcome, retry_delay

_STOP = object()


def warn(message: str) -> None:
    # Straight to stderr, never through `logging`, where a LumberHandler would send Lumber's own warnings to Lumber
    try:
        sys.stderr.write(f"[lumber] {message}\n")
    except Exception:
        pass


@dataclass
class Answer:
    status: int | None
    retry_after: str | None = None
    body: bytes = b""
    error: BaseException | None = None

    def message(self) -> str | None:
        """The API's error message ({ message }), if it sent one."""
        try:
            parsed = json.loads(self.body)
        except ValueError:
            return None
        message = parsed.get("message") if isinstance(parsed, dict) else None
        return message if isinstance(message, str) else None


_ssl_context: ssl.SSLContext | None = None


def _default_ssl_context() -> ssl.SSLContext:
    global _ssl_context
    if _ssl_context is None:
        context = ssl.create_default_context()
        # Python from python.org on macOS starts with no certificates until its Install Certificates script runs: use
        # certifi's when it's installed rather than failing every send
        if not context.cert_store_stats().get("x509_ca"):
            try:
                import certifi

                context = ssl.create_default_context(cafile=certifi.where())
            except ImportError:
                pass
        _ssl_context = context
    return _ssl_context


class Transport:
    """POST /logs over one kept-alive connection, opened again when the server closes it."""

    def __init__(self, endpoint: str, token: str, user_agent: str, timeout: float) -> None:
        parts = urllib.parse.urlsplit(endpoint.rstrip("/"))
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise ValueError(f"[lumber] endpoint must be an http or https URL, got {endpoint!r}")
        self._https = parts.scheme == "https"
        self._host = parts.hostname
        self._port = parts.port
        self._path = parts.path + INGEST_PATH
        self._timeout = timeout
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": user_agent,
        }
        self._conn: http.client.HTTPConnection | None = None

    def _connect(self) -> http.client.HTTPConnection:
        if self._https:
            return http.client.HTTPSConnection(
                self._host, self._port, timeout=self._timeout, context=_default_ssl_context()
            )
        return http.client.HTTPConnection(self._host, self._port, timeout=self._timeout)

    def post(self, body: bytes) -> Answer:
        reused = self._conn is not None
        while True:
            if self._conn is None:
                self._conn = self._connect()
            try:
                self._conn.request("POST", self._path, body=body, headers=self._headers)
                response = self._conn.getresponse()
                data = response.read()
            except (http.client.RemoteDisconnected, ConnectionResetError, BrokenPipeError) as err:
                self.close()
                # A kept-alive connection the server had already closed: the log never reached it, so open a new one
                if reused:
                    reused = False
                    continue
                return Answer(None, error=err)
            except (OSError, http.client.HTTPException) as err:
                self.close()
                return Answer(None, error=err)
            if response.will_close:
                self.close()
            return Answer(response.status, response.getheader("Retry-After"), data)

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None


class Sender:
    """Queues encrypted logs and sends them from a daemon thread. enqueue() never blocks or raises.

    The thread starts with the first log, and again in a forked child (a gunicorn or uWSGI worker), which inherits the
    queue but not the thread: the child starts over with an empty queue and its own connection.
    """

    def __init__(self, transport: Callable[[], Transport], max_queue: int) -> None:
        self._make_transport = transport
        self._max_queue = max_queue
        self._closed = False
        self._paused_until = 0.0
        self._reset()

    def _reset(self) -> None:
        self._pid = os.getpid()
        self._lock = threading.Lock()
        self._queue: queue.Queue[bytes | object] = queue.Queue(maxsize=self._max_queue)
        self._transport = self._make_transport()
        self._thread: threading.Thread | None = None
        self._wake = threading.Event()
        self._full_warned = False

    def enqueue(self, body: bytes) -> None:
        if os.getpid() != self._pid:
            self._reset()
        if self._closed or time.monotonic() < self._paused_until:
            return
        if not self._start():
            return
        try:
            self._queue.put_nowait(body)
            self._full_warned = False
        except queue.Full:
            if not self._full_warned:
                self._full_warned = True
                warn(f"dropping logs: {self._max_queue} are already waiting to send")

    def _start(self) -> bool:
        if self._thread is not None:
            return True
        with self._lock:
            if self._thread is None:
                thread = threading.Thread(target=self._run, name="lumber", daemon=True)
                try:
                    thread.start()
                except RuntimeError:
                    # The interpreter is shutting down and won't start threads
                    return False
                self._thread = thread
        return True

    def flush(self, timeout: float | None = None) -> bool:
        """Waits until every queued log is sent or dropped. False when `timeout` (seconds) ran out first."""
        if os.getpid() != self._pid or self._thread is None:
            return True
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._queue.all_tasks_done:
            while self._queue.unfinished_tasks:
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    return False
                self._queue.all_tasks_done.wait(remaining)
        return True

    def close(self, timeout: float | None = None) -> bool:
        """Sends what's queued (up to `timeout` seconds) and stops. Logs after this are dropped."""
        flushed = self.flush(timeout)
        self._closed = True
        self._wake.set()
        if self._thread is not None and os.getpid() == self._pid:
            try:
                self._queue.put(_STOP, timeout=0.1)
            except queue.Full:
                pass
        self._transport.close()
        return flushed

    def _run(self) -> None:
        # The thread keeps the queue and connection it started with: after a fork, the child's are new ones
        pending, transport = self._queue, self._transport
        while True:
            body = pending.get()
            try:
                if body is _STOP:
                    return
                assert isinstance(body, bytes)
                self._deliver(body, pending, transport)
            except Exception as err:
                warn(f"send error: {err!r}")
            finally:
                pending.task_done()

    def _deliver(self, body: bytes, pending: queue.Queue[bytes | object], transport: Transport) -> None:
        failed = 0
        while not self._closed:
            if time.monotonic() < self._paused_until:
                return
            answer = transport.post(body)
            outcome = delivery_outcome(answer.status)
            if outcome == "sent":
                return
            if outcome == "pause":
                self._pause(answer, pending)
                return
            if outcome == "drop":
                # A bad key or a malformed log won't go through on a later try
                message = answer.message()
                warn(f"log refused: HTTP {answer.status}" + (f" ({message})" if message else ""))
                return
            warn(f"send failed: HTTP {answer.status}" if answer.status is not None else f"send error: {answer.error!r}")
            failed += 1
            if failed >= MAX_ATTEMPTS:
                warn(f"dropping log after {MAX_ATTEMPTS} failed attempts")
                return
            if self._wake.wait(retry_delay(failed)):
                return

    def _pause(self, answer: Answer, pending: queue.Queue[bytes | object]) -> None:
        """Stops sending until the API's Retry-After (the start of the next month, for the monthly cap), dropping what's
        queued, with one warning for the whole pause."""
        try:
            seconds = float(answer.retry_after or "")
        except ValueError:
            seconds = 0.0
        if not seconds > 0:
            seconds = PAUSE
        self._paused_until = time.monotonic() + seconds
        while True:
            try:
                body = pending.get_nowait()
            except queue.Empty:
                break
            pending.task_done()
            if body is _STOP:
                pending.put_nowait(_STOP)
                break
        until = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=seconds)
        message = answer.message() or "Lumber is refusing logs for now (HTTP 429)."
        warn(f"{message} Dropping logs until {until.isoformat(timespec='seconds')}.")
