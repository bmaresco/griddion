"""Shared HTTP session for Wikimedia APIs.

Wikimedia requires a descriptive User-Agent with contact info; the default
contact is the project repo. Set FT_CONTACT (an email or URL) to override it.

All requests go through one process-wide rate limiter. A 429 pauses every
worker for the server's Retry-After, so throttling doesn't escalate.
"""

from __future__ import annotations

import os
import threading
import time

import requests

_session: requests.Session | None = None
_lock = threading.Lock()
_next_slot = 0.0      # earliest time the next request may start
_paused_until = 0.0   # set by a 429; applies to every worker
MIN_INTERVAL = float(os.environ.get("FT_MIN_INTERVAL", "0.3"))  # seconds between requests


def session() -> requests.Session:
    global _session
    if _session is None:
        contact = os.environ.get("FT_CONTACT", "https://github.com/bmaresco/griddion")
        _session = requests.Session()
        _session.headers["User-Agent"] = f"football-trivia-refresh/0.1 ({contact})"
        adapter = requests.adapters.HTTPAdapter(pool_connections=16, pool_maxsize=16)
        _session.mount("https://", adapter)
    return _session


def _wait_turn() -> None:
    global _next_slot
    with _lock:
        start = max(time.monotonic(), _next_slot, _paused_until)
        _next_slot = start + MIN_INTERVAL
    time.sleep(max(0.0, start - time.monotonic()))


def _pause(seconds: float) -> None:
    global _paused_until
    with _lock:
        _paused_until = max(_paused_until, time.monotonic() + seconds)


def get(url: str, *, params: dict | None = None, headers: dict | None = None, retries: int = 8, ok404: bool = False):
    """Rate-limited GET; retries 429/5xx/connection errors. Raises after `retries`."""
    for attempt in range(retries):
        _wait_turn()
        try:
            r = session().get(url, params=params, headers=headers, timeout=60)
        except requests.RequestException:
            if attempt == retries - 1:
                raise
            _pause(min(60, 2 ** attempt))
            continue
        if r.status_code == 404 and ok404:
            return r
        if r.status_code in (429, 500, 502, 503, 504):
            if attempt == retries - 1:
                r.raise_for_status()
            _pause(float(r.headers.get("Retry-After") or min(60, 2 ** attempt)))
            continue
        r.raise_for_status()
        return r
    raise RuntimeError("unreachable")
