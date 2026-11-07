"""Shared HTTP session for Wikimedia APIs.

Wikimedia requires a descriptive User-Agent with contact info. Set FT_CONTACT
(an email or URL) in your environment before running a refresh.
"""

from __future__ import annotations

import os
import time

import requests

_session: requests.Session | None = None


def session() -> requests.Session:
    global _session
    if _session is None:
        contact = os.environ.get("FT_CONTACT", "set-FT_CONTACT-env-var")
        _session = requests.Session()
        _session.headers["User-Agent"] = f"football-trivia-refresh/0.1 ({contact})"
        adapter = requests.adapters.HTTPAdapter(pool_connections=16, pool_maxsize=16)
        _session.mount("https://", adapter)
    return _session


def get(url: str, *, params: dict | None = None, headers: dict | None = None, retries: int = 5, ok404: bool = False):
    """GET with backoff on 429/5xx. Returns Response (404 allowed if ok404)."""
    delay = 1.0
    for attempt in range(retries):
        try:
            r = session().get(url, params=params, headers=headers, timeout=60)
        except requests.RequestException:
            if attempt == retries - 1:
                raise
            time.sleep(delay)
            delay *= 2
            continue
        if r.status_code == 404 and ok404:
            return r
        if r.status_code in (429, 500, 502, 503, 504):
            time.sleep(float(r.headers.get("Retry-After", delay)))
            delay *= 2
            continue
        r.raise_for_status()
        return r
    r.raise_for_status()
    return r
