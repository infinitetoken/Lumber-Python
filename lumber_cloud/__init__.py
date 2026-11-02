"""Lumber for Python: end-to-end encrypted cloud logging.

    import lumber_cloud as lumber

    lumber.config(api_key=os.environ["LUMBER_API_KEY"])
    lumber.info("Server started", port=8000)

Or send `logging` to Lumber with LumberHandler, or make your own LumberClient.
"""

from __future__ import annotations

from typing import Any

from ._version import __version__
from .client import LogLevel, LumberClient
from .handler import LumberHandler, lumber_level

__all__ = [
    "LogLevel",
    "LumberClient",
    "LumberHandler",
    "__version__",
    "config",
    "critical",
    "debug",
    "error",
    "exception",
    "fatal",
    "flush",
    "info",
    "lumber_level",
    "warn",
    "warning",
]

_client: LumberClient | None = None


def config(api_key: str, **options: Any) -> LumberClient:
    """Sets up the shared client the module's functions log with, and returns it. Takes LumberClient's options.

    Calling it again replaces the client: logs still queued in the old one keep sending in the background, but flush()
    only waits for the new one's.
    """
    global _client
    _client = LumberClient(api_key, **options)
    return _client


def _shared() -> LumberClient:
    if _client is None:
        raise RuntimeError("[lumber] Call lumber_cloud.config() before logging.")
    return _client


def debug(message: Any, /, **data: Any) -> None:
    _shared()._log(LogLevel.DEBUG, message, data)


def info(message: Any, /, **data: Any) -> None:
    _shared()._log(LogLevel.INFO, message, data)


def warn(message: Any, /, **data: Any) -> None:
    _shared()._log(LogLevel.WARN, message, data)


def error(message: Any, /, **data: Any) -> None:
    _shared()._log(LogLevel.ERROR, message, data)


def exception(message: Any, /, **data: Any) -> None:
    data.setdefault("exc_info", True)
    _shared()._log(LogLevel.ERROR, message, data)


def fatal(message: Any, /, **data: Any) -> None:
    _shared()._log(LogLevel.FATAL, message, data)


warning = warn
critical = fatal


def flush(timeout: float | None = None) -> bool:
    """Waits until every log the shared client queued is sent. False when `timeout` seconds ran out first."""
    return _shared().flush(timeout)
