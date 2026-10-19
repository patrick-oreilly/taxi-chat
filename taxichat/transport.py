"""JSON-over-HTTP transports for the model APIs, with record and replay.

Jev and DeepSeek are both reached through a Transport: a callable that takes a
request body and returns the parsed JSON response. The pipeline never knows
which kind it has, so tests can replay recorded responses offline.

Recordings are keyed by a hash of the canonical request body. If a prompt or
question definition changes, the hash changes and replay fails loudly instead
of returning a response to a request that's no longer being made.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Callable

import httpx

Transport = Callable[[dict], dict]

RETRY_STATUSES = {429, 500, 502, 503, 504}


def request_key(body: dict) -> str:
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


class HttpTransport:
    def __init__(self, url: str, api_key: str, *, timeout: float = 30.0, attempts: int = 4, headers: dict | None = None):
        if not api_key:
            raise ValueError(f"no API key for {url}")
        self.url = url
        self.attempts = attempts
        self.client = httpx.Client(
            timeout=timeout,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json", **(headers or {})},
        )

    def __call__(self, body: dict) -> dict:
        for attempt in range(1, self.attempts + 1):
            try:
                response = self.client.post(self.url, json=body)
            except httpx.TransportError:
                if attempt == self.attempts:
                    raise
            else:
                if response.status_code not in RETRY_STATUSES or attempt == self.attempts:
                    response.raise_for_status()
                    return response.json()
                retry_after = response.headers.get("retry-after")
                if retry_after and retry_after.isdigit():
                    time.sleep(int(retry_after))
                    continue
            time.sleep(0.5 * 2**attempt)
        raise AssertionError("unreachable")


class RecordingTransport:
    """Calls a real transport and saves each request/response pair to a JSON file."""

    def __init__(self, inner: Transport, path: Path):
        self.inner = inner
        self.path = path
        self.recordings = json.loads(path.read_text()) if path.exists() else {}

    def __call__(self, body: dict) -> dict:
        response = self.inner(body)
        self.recordings[request_key(body)] = {"request": body, "response": response}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.recordings, indent=2, sort_keys=True, ensure_ascii=False))
        return response


class MissingRecording(LookupError):
    pass


class ReplayTransport:
    """Serves recorded responses; raises if a request was never recorded."""

    def __init__(self, path: Path):
        self.path = path
        self.recordings = json.loads(path.read_text()) if path.exists() else {}

    def __call__(self, body: dict) -> dict:
        key = request_key(body)
        if key not in self.recordings:
            raise MissingRecording(
                f"no recording for request {key} in {self.path.name}; re-record with RECORD=1 "
                f"(the request changed, or this question was never recorded)"
            )
        return self.recordings[key]["response"]
