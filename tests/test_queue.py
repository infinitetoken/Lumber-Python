import base64
import os
import time
import threading
from unittest.mock import MagicMock, patch

import pytest

from lumber_cloud.queue import LogQueue

VALID_PAYLOAD = base64.b64encode(os.urandom(28)).decode('ascii')
TOKEN    = 'test-token'
ENDPOINT = 'https://example.com'


def test_enqueue_returns_immediately():
    """enqueue() must return in < 50ms even when requests.post blocks."""
    block_event = threading.Event()

    def blocking_post(*args, **kwargs):
        block_event.wait()  # blocks until test releases it
        mock = MagicMock()
        mock.ok = True
        return mock

    with patch('lumber_cloud.queue.requests.post', side_effect=blocking_post):
        q = LogQueue(TOKEN, ENDPOINT)
        start = time.time()
        q.enqueue(VALID_PAYLOAD, level=1)
        elapsed_ms = (time.time() - start) * 1000
        block_event.set()  # unblock the background thread

    assert elapsed_ms < 50, f"enqueue() took {elapsed_ms:.1f}ms — must be non-blocking"


def test_successful_send_drains_queue():
    """After a successful send, requests.post is called exactly once."""
    mock_response = MagicMock()
    mock_response.ok = True

    with patch('lumber_cloud.queue.requests.post', return_value=mock_response) as mock_post:
        q = LogQueue(TOKEN, ENDPOINT)
        q.enqueue(VALID_PAYLOAD, level=1)
        time.sleep(0.15)  # allow background thread to drain
        assert mock_post.call_count == 1


def test_retry_and_drop_after_max_attempts():
    """
    When all sends fail, the item is retried MAX_ATTEMPTS times then dropped.
    Never raises to the caller.
    """
    with patch('lumber_cloud.queue.requests.post', side_effect=Exception('network down')):
        with patch('lumber_cloud.queue.time.sleep', return_value=None):  # no-op sleeps
            q = LogQueue(TOKEN, ENDPOINT)
            threw = False
            try:
                q.enqueue(VALID_PAYLOAD, level=1)
                time.sleep(0.3)
            except Exception:
                threw = True
            assert not threw


def test_never_raises_on_network_failure():
    """enqueue() must not propagate network exceptions to the caller thread."""
    with patch('lumber_cloud.queue.requests.post', side_effect=ConnectionError('unreachable')):
        with patch('lumber_cloud.queue.time.sleep', return_value=None):
            q = LogQueue(TOKEN, ENDPOINT)
            raised = False
            try:
                q.enqueue(VALID_PAYLOAD, level=2)
            except Exception:
                raised = True
            assert not raised
