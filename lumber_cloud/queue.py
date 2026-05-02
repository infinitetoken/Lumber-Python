import queue
import sys
import threading
import time

import requests


class LogQueue:
    """
    Single daemon background thread that drains a thread-safe queue of log items.

    Callers enqueue() and return immediately. The daemon thread handles HTTP POST
    to the Lumber API with exponential backoff retry (max 5 attempts before drop).

    daemon=True is essential: without it, a Python script that calls lumber.log() and
    then exits would hang indefinitely waiting for the background thread to complete.
    """

    MAX_ATTEMPTS = 5
    BASE_DELAY   = 1.0   # seconds (doubles each retry)
    MAX_DELAY    = 30.0  # seconds (cap)

    def __init__(self, token: str, endpoint: str) -> None:
        self._token    = token
        self._endpoint = endpoint
        self._queue: queue.Queue = queue.Queue()
        self._thread = threading.Thread(target=self._drain, daemon=True)
        self._thread.start()

    def enqueue(self, payload: str, level: int, flagged: bool = False) -> None:
        """Returns immediately. Never raises."""
        self._queue.put({
            'payload':  payload,
            'level':    level,
            'flagged':  flagged,
            'attempts': 0,
        })

    def _drain(self) -> None:
        while True:
            item = self._queue.get()
            if self._send(item):
                self._queue.task_done()
            else:
                item['attempts'] += 1
                if item['attempts'] >= self.MAX_ATTEMPTS:
                    print(
                        f"[lumber] dropping log after {self.MAX_ATTEMPTS} failed attempts",
                        file=sys.stderr,
                    )
                    self._queue.task_done()
                else:
                    delay = min(
                        self.BASE_DELAY * (2 ** (item['attempts'] - 1)),
                        self.MAX_DELAY,
                    )
                    time.sleep(delay)
                    # Re-enqueue for next attempt
                    self._queue.put(item)
                    self._queue.task_done()

    def _send(self, item: dict) -> bool:
        try:
            r = requests.post(
                f"{self._endpoint}/logs",
                json={
                    'payload': item['payload'],
                    'level':   item['level'],
                    'flagged': item.get('flagged', False),
                },
                headers={'Authorization': f"Bearer {self._token}"},
                timeout=10,
            )
            return r.ok
        except Exception:
            return False
