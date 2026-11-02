from __future__ import annotations

import base64
import json
import math
import os
from collections.abc import Mapping
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from ._contract import KEY_VERSION, NONCE_BYTES, TAG_BYTES


def seal(aead: AESGCM, plaintext: bytes, nonce: bytes) -> bytes:
    """AES-256-GCM in Lumber's layout: the 16-byte auth tag, then the ciphertext. `cryptography` puts the tag last."""
    sealed = aead.encrypt(nonce, plaintext, None)
    return sealed[-TAG_BYTES:] + sealed[:-TAG_BYTES]


def encrypt(aead: AESGCM, payload: Mapping[str, Any]) -> dict[str, Any]:
    """A payload as POST /logs' `encrypted`, under a fresh random nonce. Never reuse a nonce with the same key."""
    nonce = os.urandom(NONCE_BYTES)
    return {
        "nonce": base64.b64encode(nonce).decode("ascii"),
        "payload": base64.b64encode(seal(aead, to_json(payload), nonce)).decode("ascii"),
        "keyVersion": KEY_VERSION,
    }


def to_json(value: Any) -> bytes:
    """Compact UTF-8 JSON the Lumber apps can always parse. Anything JSON has no type for goes in as text (a datetime as
    ISO 8601), and when that isn't enough (a NaN, which isn't JSON, or a structure that contains itself) the value is
    cleaned first, rather than a log being lost."""
    try:
        text = json.dumps(value, separators=(",", ":"), ensure_ascii=False, allow_nan=False, default=_text)
    except (TypeError, ValueError, RecursionError):
        text = json.dumps(
            _clean(value, set()), separators=(",", ":"), ensure_ascii=False, allow_nan=False, default=_text
        )
    return text.encode("utf-8")


def _text(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, (set, frozenset, tuple)):
        return list(value)
    if isinstance(value, (bytes, bytearray)):
        return bytes(value).decode("utf-8", "replace")
    return str(value)


def _clean(value: Any, seen: set[int]) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if id(value) in seen:
        return "[Circular]"
    if isinstance(value, Mapping):
        seen.add(id(value))
        cleaned: Any = {str(key): _clean(item, seen) for key, item in value.items()}
    elif isinstance(value, (list, tuple, set, frozenset)):
        seen.add(id(value))
        cleaned = [_clean(item, seen) for item in value]
    else:
        return _text(value)
    seen.discard(id(value))
    return cleaned
