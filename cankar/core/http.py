"""Shared polite HTTP transport (ADR 0008).

One place defines the project UA, timeouts, rate limiting, and error raising -
both crawl sources use it; tests inject a fake transport by subclassing.
"""

from __future__ import annotations

import time

import requests

UA = "CankarGTP-corpus-builder/0.1 (+https://nextgen-solutions.xyz; educational project)"
DEFAULT_SLEEP = 0.5  # polite delay between requests, seconds
DEFAULT_TIMEOUT = 60


class PoliteSession:
    """requests.Session wrapper: project UA, per-request delay, raise_for_status."""

    def __init__(self, sleep: float = DEFAULT_SLEEP, timeout: int = DEFAULT_TIMEOUT):
        self.sleep = sleep
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers["User-Agent"] = UA

    def get(self, url: str, **kwargs: object) -> requests.Response:
        resp = self.session.get(url, timeout=self.timeout, **kwargs)  # type: ignore[arg-type]
        resp.raise_for_status()
        time.sleep(self.sleep)
        return resp
