"""
lumber-cloud — Python logging plugin for Lumber.

Usage:
    from lumber_cloud import LumberClient, LogLevel

    lumber = LumberClient(
        token="your-app-token",
        key="your-base64-encryption-key",
    )
    lumber.log("Something happened", level=LogLevel.Info)
"""

import base64

from .encrypt import encrypt_payload
from .queue import LogQueue
from .types import LogLevel

__all__ = ['LumberClient', 'LogLevel']


class LumberClient:
    """
    Encrypts log payloads with AES-256-GCM and sends them to the Lumber API
    on a daemon background thread. All log() calls return immediately.

    Constructor raises ValueError if key does not decode to exactly 32 bytes.
    """

    def __init__(
        self,
        token: str,
        key: str,
        endpoint: str = "https://lumber-api.vercel.app",
    ) -> None:
        # Fail fast: validate key decodes to 32 bytes before spinning up the thread
        key_bytes = base64.b64decode(key)
        if len(key_bytes) != 32:
            raise ValueError(
                f"Invalid encryption key: expected 32 bytes after base64 decode, "
                f"got {len(key_bytes)}. Pass the key exactly as returned by POST /apps."
            )
        self._key   = key
        self._queue = LogQueue(token, endpoint)

    def log(
        self,
        message: str = None,
        *,
        code:    str = None,
        line:    int = None,
        column:  int = None,
        method:  str = None,
        note:    str = None,
        level:   LogLevel = LogLevel.Info,
        flagged: bool = False,
    ) -> None:
        """
        Encrypts and enqueues a log entry. Returns immediately. Never raises.

        Only non-None fields are included in the encrypted payload, matching
        Lumber-Node's behavior where undefined fields are absent from JSON.stringify().
        """
        payload = {
            k: v for k, v in {
                'message': message,
                'code':    code,
                'line':    line,
                'column':  column,
                'method':  method,
                'note':    note,
            }.items() if v is not None
        }
        try:
            encrypted = encrypt_payload(payload, self._key)
        except Exception:
            # encrypt_payload only raises on key length errors caught at __init__ — defensive
            return
        self._queue.enqueue(encrypted, int(level), flagged)
