"""Lumber-Kit's contract (tests/contract, synced by scripts/sync_contract.py): the same known answers Lumber-Node and
Lumber-Go are tested against."""

from __future__ import annotations

import base64
from typing import Any

import jsonschema
import pytest
from conftest import API_KEY, KEY, VECTORS, decrypt, schema_for
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from lumber_cloud import LogLevel, LumberClient, _contract, _crypto

CONSTANTS = VECTORS["constants"]


def named(vectors: list[dict[str, Any]]) -> Any:
    return pytest.mark.parametrize("vector", vectors, ids=[v.get("name", str(v.get("status"))) for v in vectors])


def test_constants() -> None:
    assert CONSTANTS["defaultEndpoint"] == _contract.DEFAULT_ENDPOINT
    assert CONSTANTS["ingestPath"] == _contract.INGEST_PATH
    assert CONSTANTS["keyVersion"] == _contract.KEY_VERSION
    assert CONSTANTS["keyBytes"] == _contract.KEY_BYTES
    assert CONSTANTS["nonceBytes"] == _contract.NONCE_BYTES
    assert CONSTANTS["tagBytes"] == _contract.TAG_BYTES
    assert {level.name.lower(): level.value for level in LogLevel} == CONSTANTS["levels"]
    delivery = CONSTANTS["delivery"]
    assert delivery["maxAttempts"] == _contract.MAX_ATTEMPTS
    assert delivery["baseDelayMs"] == _contract.BASE_DELAY * 1000
    assert delivery["maxDelayMs"] == _contract.MAX_DELAY * 1000
    assert delivery["pauseMs"] == _contract.PAUSE * 1000


@named(VECTORS["apiKeys"])
def test_api_keys(vector: dict[str, Any]) -> None:
    assert _contract.split_api_key(vector["apiKey"]) == (vector["token"], vector["encryptionKey"])


@named(VECTORS["encryption"])
def test_encryption(vector: dict[str, Any]) -> None:
    aead = AESGCM(base64.b64decode(vector["key"]))
    sealed = _crypto.seal(aead, vector["plaintext"].encode("utf-8"), base64.b64decode(vector["nonce"]))
    assert base64.b64encode(sealed).decode() == vector["payload"]


@named(VECTORS["payloads"])
def test_payloads(vector: dict[str, Any]) -> None:
    payload = _contract.build_payload(vector["level"], vector["message"], vector.get("data"), vector.get("autoContext"))
    assert payload == vector["payload"]
    jsonschema.validate(payload, schema_for("LogPayload"))


# Through the whole client: what it sends is a LogIngestBody whose plaintext is the vector's payload. The data goes in
# with the API's names, which the client takes as they are.
@named([v for v in VECTORS["payloads"] if "autoContext" not in v])
def test_client_sends_payloads(vector: dict[str, Any], transport: Any) -> None:
    client = LumberClient(API_KEY, auto_context=False)
    client._log(LogLevel(vector["level"]), vector["message"], dict(vector.get("data") or {}))
    assert client.flush(5)

    body = transport.instances[0].bodies[0]
    jsonschema.validate(body, schema_for("LogIngestBody"))
    assert body["level"] == vector["level"]
    assert body["encrypted"]["keyVersion"] == CONSTANTS["keyVersion"]
    assert len(base64.b64decode(body["encrypted"]["nonce"])) == CONSTANTS["nonceBytes"]
    assert decrypt(body) == vector["payload"]


@named(VECTORS["deliveryOutcomes"])
def test_delivery_outcomes(vector: dict[str, Any]) -> None:
    assert _contract.delivery_outcome(vector["status"]) == vector["outcome"]


@named(VECTORS["retryDelaysMs"])
def test_retry_delays(vector: dict[str, Any]) -> None:
    assert _contract.retry_delay(vector["failedAttempts"]) * 1000 == vector["delayMs"]


def test_default_endpoint(transport: Any) -> None:
    LumberClient(API_KEY)
    assert transport.instances[0].endpoint == CONSTANTS["defaultEndpoint"]
    assert KEY in API_KEY
