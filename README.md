# lumber-cloud

Python client for [Lumber](https://lumber.infinitetoken.com): cloud logging with end-to-end encryption. Every log is encrypted with AES-256-GCM before it leaves your process, so Lumber's servers store only ciphertext plus each log's level (kept readable for filtering and push alerts). You read your logs in the Lumber app, which decrypts them on your device.

Its one dependency is [`cryptography`](https://cryptography.io). Logs are sent from a background thread over Python's own HTTP client, so logging never waits on the network.

## Installation

```bash
pip install lumber-cloud
```

Python 3.9 or later.

## Quick start

```python
import os
import lumber_cloud as lumber

lumber.config(api_key=os.environ["LUMBER_API_KEY"])

lumber.info("Server started", port=8000)
lumber.warn("Rate limit approaching", request_id="req-123", user_id=456)
lumber.error("Payment failed", trace_id="trace-abc", order_id=789)
```

Call `config()` once at startup; every module that imports `lumber_cloud` then logs with the same client. Logs still queued when your program exits get up to 5 seconds to send.

## Getting your API key

Create an app in the Lumber app and it takes you straight to adding an API key. The key is shown only once, so copy it right away. Any device holding the app's key can add more from the app's **Secrets** screen, one per deployment if you like.

An API key is two values joined by a dot: a token, then the app's encryption key. The client sends only the token to Lumber and encrypts every log with the rest, so the encryption key never leaves your process. Keep the API key in an environment variable or your secrets manager, never in source control.

## With `logging`

`LumberHandler` sends records from Python's `logging` to Lumber, so the loggers your code and its libraries already use go there too.

```python
import logging
import os
from lumber_cloud import LumberHandler

logging.basicConfig(level=logging.INFO)  # keep printing to the console
logging.getLogger().addHandler(LumberHandler(os.environ["LUMBER_API_KEY"]))

log = logging.getLogger(__name__)
log.info("Report ready in %.1fs", 2.4, extra={"request_id": "req-123", "rows": 1500})

try:
    charge(order)
except PaymentError:
    log.exception("Payment failed")  # sent at ERROR with the traceback
```

Each record becomes a log at the matching level (CRITICAL is FATAL). Its message is the record's message with its arguments filled in. `extra=` keys go into the log's metadata, except `request_id` and `trace_id`, which are the log's own fields, and `context`, which goes into its context. The logger's name, file, line and function go into the context too.

In Django, add it to `LOGGING`:

```python
LOGGING = {
    "version": 1,
    "handlers": {
        "lumber": {"class": "lumber_cloud.LumberHandler", "api_key": os.environ["LUMBER_API_KEY"], "level": "INFO"},
    },
    "root": {"handlers": ["lumber"], "level": "INFO"},
}
```

To share one client between a handler and your own calls, pass it: `LumberHandler(client=lumber.config(api_key=...))`.

## Log methods

| Method | Level |
|--------|-------|
| `debug(message, **data)` | DEBUG |
| `info(message, **data)` | INFO |
| `warn(message, **data)`, `warning(...)` | WARN |
| `error(message, **data)` | ERROR |
| `exception(message, **data)` | ERROR, with the exception being handled |
| `fatal(message, **data)`, `critical(...)` | FATAL |
| `flush(timeout=None)` | Waits for queued logs to send; `False` if `timeout` seconds ran out first |

The module's functions log with the client `config()` made. `LumberClient` has the same methods, for when you need more than one.

## Data

Keyword arguments become the log's fields:

```python
lumber.info(
    "User signed in",
    request_id="req-abc",           # the log's request ID
    trace_id="trace-xyz",           # the log's trace ID
    context={"region": "us-east"},  # merged into its context
    metadata={"plan": "pro"},       # merged into its metadata
    user_id=123,                    # any other keyword goes into metadata
    exc_info=err,                   # an exception (or True for the one being handled)
)
```

An explicit `metadata` key wins over a colliding keyword. An exception goes into metadata as `exception` (`ValueError: bad amount`) and `traceback`. Values JSON can't hold are sent as text (a `datetime` as ISO 8601, a set as a list), and a NaN as null. Everything, message included, is encrypted.

## Options

```python
lumber.config(
    api_key=os.environ["LUMBER_API_KEY"],
    environment="production",  # sent as `env` in every log's context
    auto_context=True,         # send the process id and hostname with every log
    caller=False,              # also send the file, line and function that logged
    caller_depth=0,            # frames to skip for `caller`, one per wrapper around Lumber
    timeout=10.0,              # seconds to wait for Lumber to answer one log
    max_queue=10_000,          # logs waiting to send before new ones are dropped
    shutdown_timeout=5.0,      # seconds queued logs get when the program exits
)
```

## Delivery

Logs are sent in order, one `POST /logs` per log, from a daemon thread over a connection kept open between logs. A network error or a 5xx counts as a failed attempt: each log gets 5, waiting 1, 2, 4, then 8 seconds between them, and is then dropped with a warning on stderr. A log Lumber refuses (a 4xx, such as an invalid API key) is dropped at once with a warning, since sending it again won't help. When your team has sent its plan's logs for the month, Lumber answers 429: the client warns once and drops logs until the month turns. While Lumber can't be reached, up to `max_queue` logs wait; past that, new ones are dropped.

Forking servers (gunicorn, uWSGI) are handled: a worker process starts its own sending thread and connection with its first log.

## Development

```bash
python -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/pytest && .venv/bin/ruff check . && .venv/bin/mypy
```

`tests/contract` holds [Lumber-Kit](https://github.com/infinitetoken/lumber-kit)'s contract at the version in `tests/contract/VERSION`: a JSON Schema of the wire format and known answers for API keys, encryption, payloads and delivery, which Lumber's Node and Go clients are tested against too. `python scripts/sync_contract.py 0.8.0` moves it to a new kit version.

## License

MIT. See `LICENSE`.
