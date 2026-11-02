"""Lumber-Kit's contract in Python: the constants, API key format, payload and delivery rules every Lumber plugin
shares. tests/contract holds the kit's schema and known answers, which everything here is tested against."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

DEFAULT_ENDPOINT = "https://api.lumber.infinitetoken.com"
INGEST_PATH = "/logs"
KEY_VERSION = 1
KEY_BYTES = 32
NONCE_BYTES = 12
TAG_BYTES = 16

# Delivery (Lumber-Kit's logDelivery), in seconds
MAX_ATTEMPTS = 5
BASE_DELAY = 1.0
MAX_DELAY = 30.0
PAUSE = 60 * 60.0

Outcome = Literal["sent", "retry", "drop", "pause"]


def split_api_key(api_key: str) -> tuple[str, str | None]:
    """An API key's token and encryption key (`<token>.<encryptionKey>`). A value with no dot is all token."""
    value = api_key.strip()
    token, dot, encryption_key = value.partition(".")
    return (token, encryption_key) if dot else (value, None)


def build_payload(
    level: int,
    message: str,
    data: Mapping[str, Any] | None = None,
    auto_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """The plaintext a log call encrypts. requestId and traceId become the payload's own fields, the call's context goes
    over the automatic context, and every other key goes into metadata, where an explicit metadata key wins. A context
    or metadata that isn't a mapping is kept as an ordinary metadata key, and a None one is left out."""
    rest = dict(data or {})
    request_id = rest.pop("requestId", None)
    trace_id = rest.pop("traceId", None)
    given_context = rest.pop("context", None)
    given_metadata = rest.pop("metadata", None)

    context = given_context if isinstance(given_context, Mapping) else None
    metadata = given_metadata if isinstance(given_metadata, Mapping) else None
    if given_context is not None and context is None:
        rest["context"] = given_context
    if given_metadata is not None and metadata is None:
        rest["metadata"] = given_metadata

    merged_metadata = {**rest, **(metadata or {})} if rest else (dict(metadata) if metadata is not None else None)
    merged_context = (
        {**auto_context, **(context or {})} if auto_context else (dict(context) if context is not None else None)
    )

    payload: dict[str, Any] = {"level": int(level), "message": message}
    if request_id is not None:
        payload["requestId"] = request_id
    if trace_id is not None:
        payload["traceId"] = trace_id
    if merged_context is not None:
        payload["context"] = merged_context
    if merged_metadata is not None:
        payload["metadata"] = merged_metadata
    return payload


def delivery_outcome(status: int | None) -> Outcome:
    """What to do with a log once POST /logs answers with `status`, or None for no answer (a network error)."""
    if status is None:
        return "retry"
    if 200 <= status < 300:
        return "sent"
    if status == 429:
        return "pause"
    if 400 <= status < 500:
        return "drop"
    return "retry"


def retry_delay(failed_attempts: int) -> float:
    """Seconds to wait before trying a log again after its nth failure: 1, 2, 4 and so on, up to 30."""
    return min(BASE_DELAY * float(2 ** max(0, failed_attempts - 1)), MAX_DELAY)
