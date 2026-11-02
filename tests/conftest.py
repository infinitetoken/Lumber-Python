from __future__ import annotations

import base64
import json
import threading
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from lumber_cloud import _delivery
from lumber_cloud._delivery import Answer

CONTRACT = Path(__file__).parent / "contract"
VECTORS = json.loads((CONTRACT / "vectors.json").read_text())
SCHEMA = json.loads((CONTRACT / "schema.json").read_text())

KEY = VECTORS["encryption"][0]["key"]
API_KEY = f"3f9c0e7a1b2d4c6e8f0a1b2c3d4e5f60.{KEY}"


def schema_for(name: str) -> dict[str, Any]:
    """One of the kit's types as a schema of its own."""
    return {"$schema": SCHEMA["$schema"], "$ref": f"#/definitions/{name}", "definitions": SCHEMA["definitions"]}


def decrypt(body: dict[str, Any], key: str = KEY) -> dict[str, Any]:
    tag_bytes = VECTORS["constants"]["tagBytes"]
    sealed = base64.b64decode(body["encrypted"]["payload"])
    nonce = base64.b64decode(body["encrypted"]["nonce"])
    plaintext = AESGCM(base64.b64decode(key)).decrypt(nonce, sealed[tag_bytes:] + sealed[:tag_bytes], None)
    return json.loads(plaintext)


class FakeTransport:
    """Stands in for the HTTP connection: records each body and answers from a script (201 once it runs out)."""

    instances: list[FakeTransport] = []

    def __init__(self, endpoint: str, token: str, user_agent: str, timeout: float) -> None:
        self.endpoint = endpoint
        self.token = token
        self.user_agent = user_agent
        self.bodies: list[dict[str, Any]] = []
        self.answers: list[Answer] = []
        self.block = threading.Event()
        self.block.set()
        self.closed = False
        FakeTransport.instances.append(self)

    def post(self, body: bytes) -> Answer:
        self.block.wait()
        self.bodies.append(json.loads(body))
        return self.answers.pop(0) if self.answers else Answer(201)

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def transport(monkeypatch: pytest.MonkeyPatch) -> type[FakeTransport]:
    FakeTransport.instances = []
    monkeypatch.setattr("lumber_cloud.client.Transport", FakeTransport)
    # Retries wait 1s, 2s, 4s...: the contract test checks those, everything else retries at once
    monkeypatch.setattr(_delivery, "retry_delay", lambda failed: 0.0)
    return FakeTransport


@pytest.fixture
def warnings(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    seen: list[str] = []
    monkeypatch.setattr(_delivery, "warn", seen.append)
    return seen
