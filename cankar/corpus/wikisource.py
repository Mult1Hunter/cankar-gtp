"""Shared sl.wikisource (Wikivir) MediaWiki API helpers.

Used by scripts/crawl_wikivir.py and scripts/build_registry.py - one polite
client, one UA, one place to change API behavior.
"""

from __future__ import annotations

import time

import requests

API = "https://sl.wikisource.org/w/api.php"
UA = "CankarGTP-corpus-builder/0.1 (+https://nextgen-solutions.xyz; educational project)"
SLEEP = 0.5  # polite delay between API calls, seconds
BATCH = 50  # max titles per content request (API limit for non-bots)


def make_session() -> requests.Session:
    session = requests.Session()
    session.headers["User-Agent"] = UA
    return session


def api_get(session: requests.Session, params: dict) -> dict:
    params = {"format": "json", "formatversion": "2", **params}
    resp = session.get(API, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"API error: {data['error']}")
    time.sleep(SLEEP)
    return data


def fetch_wikitext(session: requests.Session, titles: list[str]) -> dict[str, str]:
    """Raw wikitext for any number of titles, BATCH per request."""
    result: dict[str, str] = {}
    for i in range(0, len(titles), BATCH):
        chunk = titles[i : i + BATCH]
        data = api_get(
            session,
            {
                "action": "query",
                "prop": "revisions",
                "rvprop": "content",
                "rvslots": "main",
                "titles": "|".join(chunk),
            },
        )
        for page in data["query"]["pages"]:
            if page.get("missing") or not page.get("revisions"):
                continue
            result[page["title"]] = page["revisions"][0]["slots"]["main"]["content"]
    return result
