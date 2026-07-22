"""Wikivir (sl.wikisource) crawling: API client + the full crawl flow.

Absorbs the former wikisource.py client and scripts/corpus/crawl_wikivir.py
(ADR 0007: scripts/ abolished - all logic is importable, the CLI is a thin
subcommand in cankar.corpus.cli).

Recon facts (2026-07): sl.wikisource has NO Avtor: namespace - author indexes
are plain ns-0 pages; category listings are richer than index pages (Cankar:
217 vs 128); long works are not split into subpages.
"""

from __future__ import annotations

import sys
import time

import requests

from cankar.core.manifest import ShardManifest, git_sha, sha256_of, utc_now_iso, write_manifest
from cankar.core.paths import dataset_manifest
from cankar.core.schema import CorpusDoc
from cankar.corpus.clean import (
    clean_wikitext,
    is_by_other_author,
    is_index_title,
    is_redirect,
    looks_like_index,
)

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


def titles_from_category(session: requests.Session, category: str) -> list[str]:
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


def titles_from_author_page(session: requests.Session, author_page: str) -> list[str]:
    """ns-0 links from an author index page (the author's work list)."""
    data = api_get(session, {"action": "parse", "page": author_page, "prop": "links"})
    links = data["parse"]["links"]
    return [link["title"] for link in links if link.get("ns") == 0 and link.get("exists", True)]


def expand_subpages(session: requests.Session, titles: list[str]) -> list[str]:
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
    out,
    author_label: str | None = None,
    source: str = "wikivir",
    min_chars: int = 400,
    expand: bool = False,
    expected_band: str | None = None,
    not_by: list[str] | None = None,
) -> dict[str, int]:
    """Full crawl flow: list, guard, fetch, clean, write shard + committed manifest."""
    not_by = not_by or []
    session = make_session()

    titles: list[str] = []
    for cat in categories:
        print(f"listing {cat} ...", file=sys.stderr)
        titles += titles_from_category(session, cat)
    for page in author_pages:
        print(f"listing links on {page} ...", file=sys.stderr)
        titles += titles_from_author_page(session, page)

    # author index pages and Seznam/list pages are catalogs, not literature
    excluded = set(author_pages) | {t for t in set(titles) if is_index_title(t)}
    titles = sorted(set(titles) - excluded)
    print(
        f"{len(titles)} unique titles ({len(excluded)} index/list pages excluded)", file=sys.stderr
    )

    if expand:
        titles = sorted(set(expand_subpages(session, titles)))
        print(f"{len(titles)} titles after subpage expansion", file=sys.stderr)

    print(f"fetching {len(titles)} pages ...", file=sys.stderr)
    pages = fetch_wikitext(session, titles)

    out.parent.mkdir(parents=True, exist_ok=True)
    stats = {"docs": 0, "chars": 0, "words": 0, "skipped": 0, "misattributed": 0, "index_docs": 0}
    with out.open("w", encoding="utf-8") as f:
        for title, wikitext in sorted(pages.items()):
            if is_redirect(wikitext):
                stats["skipped"] += 1
                continue
            true_author = is_by_other_author(title, not_by)
            if true_author:
                print(
                    f"  attribution guard: {title!r} is by {true_author} - skipped", file=sys.stderr
                )
                stats["misattributed"] += 1
                continue
            text = clean_wikitext(wikitext)
            if len(text) < min_chars:
                stats["skipped"] += 1
                continue
            if looks_like_index(text):
                print(
                    f"  index-content guard: {title!r} looks like a bibliography - skipped",
                    file=sys.stderr,
                )
                stats["index_docs"] += 1
                continue
            doc = CorpusDoc(
                title=title,
                url=f"https://sl.wikisource.org/wiki/{title.replace(' ', '_')}",
                text=text,
                n_chars=len(text),
                source=source,
                author=author_label,
            )
            f.write(doc.model_dump_json() + "\n")
            stats["docs"] += 1
            stats["chars"] += len(text)
            stats["words"] += len(text.split())

    manifest = ShardManifest(
        source=source,
        script="cankar corpus crawl-wikivir",
        git_sha=git_sha(),
        retrieved_at=utc_now_iso(),
        args={
            "category": categories,
            "author": author_pages,
            "expand_subpages": expand,
            "min_chars": min_chars,
            "author_label": author_label,
        },
        n_docs=stats["docs"],
        n_chars=stats["chars"],
        n_words=stats["words"],
        sha256=sha256_of(out),
        expected_band_words=parse_band(expected_band),
    )
    mpath = write_manifest(manifest, dataset_manifest("corpus", out.stem))

    print(
        f"\nwrote {out} (manifest: {mpath})\n"
        f"  docs:    {stats['docs']} (skipped {stats['skipped']}: redirects/too short; "
        f"{stats['misattributed']} misattributed, {stats['index_docs']} index-content)\n"
        f"  words:   {stats['words']:,}",
        file=sys.stderr,
    )
    return stats
