#!/usr/bin/env python3
"""Crawl Slovene Wikisource (Wikivir) and build a JSONL text corpus.

Phase 1 of CankarGTP (see ROADMAP.md). Pulls pages via the MediaWiki API —
no HTML scraping — strips wiki markup, NFC-normalizes, and writes one JSON
document per line.

Usage:
    # By category (repeatable):
    uv run scripts/crawl_wikivir.py \
        --category "Kategorija:Ivan Cankar" \
        --out data/corpus/cankar.jsonl

    # By author page (collects ns-0 links from an Avtor: page):
    uv run scripts/crawl_wikivir.py \
        --author "Avtor:Ivan Cankar" \
        --out data/corpus/cankar.jsonl

    # Expand subpages too (long works split as "Naslov/I", "Naslov/II", ...):
    ... --expand-subpages

NOTE: category/author page names differ per author — verify the exact name in
Wikivir's web UI first. If both modes are given, results are merged and deduped.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import unicodedata
from pathlib import Path

import mwparserfromhell
import requests

API = "https://sl.wikisource.org/w/api.php"
UA = "CankarGTP-corpus-builder/0.1 (+https://nextgen-solutions.xyz; educational project)"
SLEEP = 0.5  # polite delay between API calls, seconds
BATCH = 50  # max titles per content request (API limit for non-bots)

REDIRECT_RE = re.compile(r"^\s*#(redirect|preusmeritev)", re.IGNORECASE)


def api_get(session: requests.Session, params: dict) -> dict:
    params = {"format": "json", "formatversion": "2", **params}
    resp = session.get(API, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"API error: {data['error']}")
    time.sleep(SLEEP)
    return data


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
        members = data["query"]["categorymembers"]
        titles += [m["title"] for m in members]
        cont = data.get("continue")
        if not cont:
            return titles
        params = {**params, **cont}


def titles_from_author_page(session: requests.Session, author_page: str) -> list[str]:
    """ns-0 links from an Avtor: page (the author's work list)."""
    data = api_get(
        session,
        {"action": "parse", "page": author_page, "prop": "links"},
    )
    links = data["parse"]["links"]
    return [link["title"] for link in links if link.get("ns") == 0 and link.get("exists", True)]


def expand_subpages(session: requests.Session, titles: list[str]) -> list[str]:
    """For each title, also collect 'Title/...' subpages (chaptered works)."""
    out = list(titles)
    for title in titles:
        params = {
            "action": "query",
            "list": "allpages",
            "apprefix": f"{title}/",
            "apnamespace": "0",
            "aplimit": "500",
        }
        data = api_get(session, params)
        out += [p["title"] for p in data["query"]["allpages"]]
    return out


def fetch_wikitext(session: requests.Session, titles: list[str]) -> dict[str, str]:
    """Raw wikitext for up to BATCH titles per request."""
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
            if page.get("missing"):
                continue
            revs = page.get("revisions")
            if not revs:
                continue
            result[page["title"]] = revs[0]["slots"]["main"]["content"]
        done = min(i + BATCH, len(titles))
        print(f"  fetched {done}/{len(titles)} pages", file=sys.stderr)
    return result


def clean(wikitext: str) -> str:
    """Wiki markup -> plain text. NFC-normalized (č/š/ž NFD bugs are real)."""
    code = mwparserfromhell.parse(wikitext)
    text = code.strip_code(normalize=True, collapse=True)
    text = unicodedata.normalize("NFC", text)
    # collapse 3+ newlines, strip trailing spaces per line
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--category", action="append", default=[], help="Kategorija:... (repeatable)")
    ap.add_argument("--author", action="append", default=[], help="Avtor:... page (repeatable)")
    ap.add_argument("--out", required=True, type=Path, help="output JSONL path")
    ap.add_argument("--expand-subpages", action="store_true", help="also fetch Title/... subpages")
    ap.add_argument("--min-chars", type=int, default=400, help="skip docs shorter than this")
    args = ap.parse_args()

    if not args.category and not args.author:
        ap.error("need at least one --category or --author")

    session = requests.Session()
    session.headers["User-Agent"] = UA

    titles: list[str] = []
    for cat in args.category:
        print(f"listing {cat} ...", file=sys.stderr)
        titles += titles_from_category(session, cat)
    for auth in args.author:
        print(f"listing links on {auth} ...", file=sys.stderr)
        titles += titles_from_author_page(session, auth)

    titles = sorted(set(titles))
    print(f"{len(titles)} unique titles", file=sys.stderr)

    if args.expand_subpages:
        titles = sorted(set(expand_subpages(session, titles)))
        print(f"{len(titles)} titles after subpage expansion", file=sys.stderr)

    pages = fetch_wikitext(session, titles)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    n_docs = n_chars = n_words = n_skipped = 0
    with args.out.open("w", encoding="utf-8") as f:
        for title, wikitext in sorted(pages.items()):
            if REDIRECT_RE.match(wikitext):
                n_skipped += 1
                continue
            text = clean(wikitext)
            if len(text) < args.min_chars:
                n_skipped += 1
                continue
            doc = {
                "title": title,
                "url": f"https://sl.wikisource.org/wiki/{title.replace(' ', '_')}",
                "text": text,
                "n_chars": len(text),
            }
            f.write(json.dumps(doc, ensure_ascii=False) + "\n")
            n_docs += 1
            n_chars += len(text)
            n_words += len(text.split())

    print(
        f"\nwrote {args.out}\n"
        f"  docs:    {n_docs} (skipped {n_skipped}: redirects/too short)\n"
        f"  chars:   {n_chars:,}\n"
        f"  words:   {n_words:,}\n"
        f"  ~tokens: {n_chars // 4:,} "
        f"(rough, chars/4 — real count comes from our tokenizer in Phase 2)",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
