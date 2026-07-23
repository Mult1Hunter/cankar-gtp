"""Wikivir (sl.wikisource) crawling: API client + the full crawl flow.

Absorbs the former wikisource.py client and scripts/corpus/crawl_wikivir.py
(ADR 0007: scripts/ abolished - all logic is importable, the CLI is a thin
subcommand in cankar.corpus.cli).

Recon facts (2026-07): sl.wikisource has NO Avtor: namespace - author indexes
are plain ns-0 pages; category listings are richer than index pages (Cankar:
217 vs 128); long works are not split into subpages.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path

from cankar.core.http import PoliteSession
from cankar.core.schema import CorpusDoc
from cankar.corpus.clean import (
    clean_wikitext,
    is_by_other_author,
    is_index_title,
    is_redirect,
    looks_like_index,
)
from cankar.corpus.shard import ShardWriter

logger = logging.getLogger(__name__)

API = "https://sl.wikisource.org/w/api.php"
BATCH = 50  # max titles per content request (API limit for non-bots)


@dataclass
class CrawlStats:
    """Typed result of a Wikivir crawl (ADR 0008: no stringly stat dicts)."""

    docs: int = 0
    chars: int = 0
    words: int = 0
    skipped: int = 0
    misattributed: int = 0
    index_docs: int = 0


def make_session() -> PoliteSession:
    return PoliteSession(sleep=0.5, timeout=30)


def api_get(session: PoliteSession, params: dict) -> dict:
    # maxlag: MediaWiki etiquette - back off when replication lag is high
    # (https://www.mediawiki.org/wiki/Manual:Maxlag_parameter)
    params = {"format": "json", "formatversion": "2", "maxlag": "5", **params}
    data = session.get(API, params=params).json()
    if "error" in data:
        if data["error"].get("code") == "maxlag":
            time.sleep(5)
            data = session.get(API, params=params).json()
            if "error" not in data:
                return data
        raise RuntimeError(f"API error: {data['error']}")
    return data


def fetch_wikitext(session: PoliteSession, titles: list[str]) -> dict[str, str]:
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


def titles_from_category(session: PoliteSession, category: str) -> list[str]:
    """All ns-0 member titles of a category, following continuation."""
    titles: list[str] = []
    params = {
        "action": "query",
        "list": "categorymembers",
        "cmtitle": category,
        "cmnamespace": "0",
        "cmlimit": "500",
    }
    while True:
        data = api_get(session, params)
        titles += [m["title"] for m in data["query"]["categorymembers"]]
        cont = data.get("continue")
        if not cont:
            return titles
        params = {**params, **cont}


def titles_from_author_page(session: PoliteSession, author_page: str) -> list[str]:
    """ns-0 links from an author index page (the author's work list)."""
    data = api_get(session, {"action": "parse", "page": author_page, "prop": "links"})
    links = data["parse"]["links"]
    return [link["title"] for link in links if link.get("ns") == 0 and link.get("exists", True)]


def expand_subpages(session: PoliteSession, titles: list[str]) -> list[str]:
    """For each title, also collect 'Title/...' subpages (chaptered works)."""
    out = list(titles)
    for title in titles:
        data = api_get(
            session,
            {
                "action": "query",
                "list": "allpages",
                "apprefix": f"{title}/",
                "apnamespace": "0",
                "aplimit": "500",
            },
        )
        out += [p["title"] for p in data["query"]["allpages"]]
    return out


def parse_band(spec: str | None) -> tuple[int, int] | None:
    if not spec:
        return None
    lo, hi = (int(x) for x in spec.split(","))
    return (lo, hi)


def crawl(
    *,
    categories: list[str],
    author_pages: list[str],
    out: Path,
    author_label: str | None = None,
    source: str = "wikivir",
    min_chars: int = 400,
    expand: bool = False,
    expected_band: str | None = None,
    not_by: list[str] | None = None,
) -> CrawlStats:
    """Full crawl flow: list, guard, fetch, clean, write shard + committed manifest."""
    not_by = not_by or []
    session = make_session()

    titles: list[str] = []
    for cat in categories:
        logger.info(f"listing {cat} ...")
        titles += titles_from_category(session, cat)
    for page in author_pages:
        logger.info(f"listing links on {page} ...")
        titles += titles_from_author_page(session, page)

    # author index pages and Seznam/list pages are catalogs, not literature
    excluded = set(author_pages) | {t for t in set(titles) if is_index_title(t)}
    titles = sorted(set(titles) - excluded)
    logger.info(f"{len(titles)} unique titles ({len(excluded)} index/list pages excluded)")

    if expand:
        titles = sorted(set(expand_subpages(session, titles)))
        logger.info(f"{len(titles)} titles after subpage expansion")

    logger.info(f"fetching {len(titles)} pages ...")
    pages = fetch_wikitext(session, titles)

    stats = CrawlStats()
    writer = ShardWriter(
        out,
        source=source,
        script="cankar corpus crawl-wikivir",
        args={
            "category": categories,
            "author": author_pages,
            "expand_subpages": expand,
            "min_chars": min_chars,
            "author_label": author_label,
        },
        expected_band=parse_band(expected_band),
    )
    with writer:
        for title, wikitext in sorted(pages.items()):
            if is_redirect(wikitext):
                stats.skipped += 1
                continue
            true_author = is_by_other_author(title, not_by)
            if true_author:
                logger.info(f"  attribution guard: {title!r} is by {true_author} - skipped")
                stats.misattributed += 1
                continue
            text = clean_wikitext(wikitext)
            if len(text) < min_chars:
                stats.skipped += 1
                continue
            if looks_like_index(text):
                logger.info(f"  index-content guard: {title!r} looks like a bibliography - skipped")
                stats.index_docs += 1
                continue
            writer.write(
                CorpusDoc(
                    title=title,
                    url=f"https://sl.wikisource.org/wiki/{title.replace(' ', '_')}",
                    text=text,
                    n_chars=len(text),
                    source=source,
                    author=author_label,
                )
            )
    stats.docs, stats.chars, stats.words = writer.n_docs, writer.n_chars, writer.n_words
    logger.info(
        f"wrote {out}: {stats.docs} docs, {stats.words:,} words "
        f"(skipped {stats.skipped} redirect/short, {stats.misattributed} misattributed, "
        f"{stats.index_docs} index-content)"
    )
    return stats
