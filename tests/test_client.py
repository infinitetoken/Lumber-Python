import base64
import os
import time
import threading
from unittest.mock import MagicMock, patch

import pytest

from lumber_cloud import LumberClient, LogLevel

TOKEN     = 'test-token'
ENDPOINT  = 'https://example.com'
VALID_KEY = base64.b64encode(os.urandom(32)).decode('ascii')


def make_client(endpoint: str = ENDPOINT) -> LumberClient:
    return LumberClient(TOKEN, VALID_KEY, endpoint)


def test_bad_key_16_bytes_raises_value_error():
    bad_key = base64.b64encode(os.urandom(16)).decode('ascii')
    with pytest.raises(ValueError, match="32 bytes"):
        LumberClient(TOKEN, bad_key, ENDPOINT)


def test_bad_key_33_bytes_raises_value_error():
    bad_key = base64.b64encode(os.urandom(33)).decode('ascii')
    with pytest.raises(ValueError, match="32 bytes"):
        LumberClient(TOKEN, bad_key, ENDPOINT)


def test_valid_construction_succeeds():
    """32-byte key must construct without error."""
    client = make_client()
    assert client is not None


def test_log_returns_immediately():
    """1000 log() calls must complete in < 50ms (encryption + enqueue is non-blocking)."""
    block_event = threading.Event()

    def blocking_post(*args, **kwargs):
        block_event.wait()
        mock = MagicMock()
        mock.ok = True
        return mock

    with patch('lumber_cloud.queue.requests.post', side_effect=blocking_post):
        client = make_client()
        start = time.time()
        for i in range(1000):
            client.log(f"msg {i}", level=LogLevel.Info)
        elapsed_ms = (time.time() - start) * 1000
        block_event.set()

    assert elapsed_ms < 50, f"1000 log() calls took {elapsed_ms:.1f}ms — must be non-blocking"


def test_payload_is_not_plaintext():
    """
    After log('secret-message'), the payload sent to requests.post must be base64 ciphertext,
    not the plaintext message. Ciphertext must not contain the plaintext string.
    """
    mock_response = MagicMock()
    mock_response.ok = True
    secret = 'my-secret-message-do-not-send-plaintext'

    with patch('lumber_cloud.queue.requests.post', return_value=mock_response) as mock_post:
        client = make_client()
        client.log(secret, level=LogLevel.Warn)
        time.sleep(0.15)

    assert mock_post.call_count == 1
    call_kwargs = mock_post.call_args
    # requests.post(url, json={...}) — extract the json kwarg
    body = call_kwargs.kwargs.get('json') or call_kwargs[1].get('json')
    payload_b64 = body['payload']

    assert secret not in payload_b64, "Plaintext was sent — encryption not applied"
    # Must be valid base64 with at least IV(12) + Tag(16) + some ciphertext
    decoded = base64.b64decode(payload_b64)
    assert len(decoded) > 28, "Ciphertext is too short to contain IV + tag + data"
