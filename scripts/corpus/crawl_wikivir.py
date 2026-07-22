#!/usr/bin/env python3
"""Crawl Slovene Wikisource (Wikivir) and build a JSONL text corpus.

Phase 1 of CankarGTP (see ROADMAP.md). Pulls pages via the MediaWiki API -
no HTML scraping - strips wiki markup, NFC-normalizes, and writes one JSON
document per line (schema: cankar.schema.CorpusDoc) plus a provenance
manifest (cankar.manifest.ShardManifest) beside the shard.

Usage:
    # By category (repeatable; the primary mode - richest listing):
    uv run scripts/crawl_wikivir.py \
        --category "Kategorija:Ivan Cankar" \
        --author-label "Ivan Cankar" \
        --expected-band 1500000,3000000 \
        --out data/corpus/cankar.jsonl

    # By author index page (ns-0 - sl.wikisource has NO Avtor: namespace;
    # the index is a plain page like "Ivan Cankar"):
    ... --author "Ivan Cankar"

    # Expand subpages too (long works split as "Naslov/I", ...):
    ... --expand-subpages

If both modes are given, results are merged and deduped. Verify exact page
names in the Wikivir web UI first; category vs author-page counts differ
(e.g. Cankar: 217 in category vs 128 on the index page, 2026-07).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import requests

from cankar.core.manifest import ShardManifest, git_sha, sha256_of, utc_now_iso, write_manifest
from cankar.core.schema import CorpusDoc
from cankar.corpus.clean import (
    clean_wikitext,
    is_by_other_author,
    is_index_title,
    is_redirect,
    looks_like_index,
)
from cankar.corpus.wikisource import api_get, fetch_wikitext, make_session


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
    """ns-0 links from an author index page (the author's work list)."""
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


def parse_band(spec: str | None) -> tuple[int, int] | None:
    if not spec:
        return None
    lo, hi = (int(x) for x in spec.split(","))
    return (lo, hi)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--category", action="append", default=[], help="Kategorija:... (repeatable)")
    ap.add_argument(
        "--author",
        action="append",
        default=[],
        help="author index page, e.g. 'Ivan Cankar' (repeatable; ns-0, no Avtor: prefix)",
    )
    ap.add_argument("--out", required=True, type=Path, help="output JSONL path")
    ap.add_argument("--expand-subpages", action="store_true", help="also fetch Title/... subpages")
    ap.add_argument("--min-chars", type=int, default=400, help="skip docs shorter than this")
    ap.add_argument("--source", default="wikivir", help="source tag for docs + manifest")
    ap.add_argument("--author-label", default=None, help="author attribution for all docs")
    ap.add_argument(
        "--expected-band", default=None, help="MIN,MAX expected total words (manifest sanity band)"
    )
    ap.add_argument(
        "--not-by",
        action="append",
        default=[],
        help="other roster author (repeatable): titles ending (Their Name) are "
        "essays BY them ABOUT this author - excluded (attribution guard)",
    )
    args = ap.parse_args()

    if not args.category and not args.author:
        ap.error("need at least one --category or --author")

    session = make_session()

    titles: list[str] = []
    for cat in args.category:
        print(f"listing {cat} ...", file=sys.stderr)
        titles += titles_from_category(session, cat)
    for auth in args.author:
        print(f"listing links on {auth} ...", file=sys.stderr)
        titles += titles_from_author_page(session, auth)

    # author index pages and Seznam/list pages are catalogs, not literature
    # (corpus-qa finding, first crawl: the "Ivan Cankar" index page crawled itself)
    excluded = set(args.author) | {t for t in set(titles) if is_index_title(t)}
    titles = sorted(set(titles) - excluded)
    print(
        f"{len(titles)} unique titles ({len(excluded)} index/list pages excluded)",
        file=sys.stderr,
    )

    if args.expand_subpages:
        titles = sorted(set(expand_subpages(session, titles)))
        print(f"{len(titles)} titles after subpage expansion", file=sys.stderr)

    print(f"fetching {len(titles)} pages ...", file=sys.stderr)
    pages = fetch_wikitext(session, titles)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    n_docs = n_chars = n_words = n_skipped = n_misattr = n_indexdoc = 0
    with args.out.open("w", encoding="utf-8") as f:
        for title, wikitext in sorted(pages.items()):
            if is_redirect(wikitext):
                n_skipped += 1
                continue
            true_author = is_by_other_author(title, args.not_by)
            if true_author:
                print(
                    f"  attribution guard: {title!r} is by {true_author} - skipped", file=sys.stderr
                )
                n_misattr += 1
                continue
            text = clean_wikitext(wikitext)
            if len(text) < args.min_chars:
                n_skipped += 1
                continue
            if looks_like_index(text):
                print(
                    f"  index-content guard: {title!r} looks like a bibliography - skipped",
                    file=sys.stderr,
                )
                n_indexdoc += 1
                continue
            doc = CorpusDoc(
                title=title,
                url=f"https://sl.wikisource.org/wiki/{title.replace(' ', '_')}",
                text=text,
                n_chars=len(text),
                source=args.source,
                author=args.author_label,
            )
            f.write(doc.model_dump_json() + "\n")
            n_docs += 1
            n_chars += len(text)
            n_words += len(text.split())

    manifest = ShardManifest(
        source=args.source,
        script="scripts/corpus/crawl_wikivir.py",
        git_sha=git_sha(),
        retrieved_at=utc_now_iso(),
        args={
            "category": args.category,
            "author": args.author,
            "expand_subpages": args.expand_subpages,
            "min_chars": args.min_chars,
            "author_label": args.author_label,
        },
        n_docs=n_docs,
        n_chars=n_chars,
        n_words=n_words,
        sha256=sha256_of(args.out),
        expected_band_words=parse_band(args.expected_band),
    )
    mpath = write_manifest(args.out, manifest)

    print(
        f"\nwrote {args.out} (+ {mpath.name})\n"
        f"  docs:    {n_docs} (skipped {n_skipped}: redirects/too short; "
        f"{n_misattr} misattributed, {n_indexdoc} index-content)\n"
        f"  chars:   {n_chars:,}\n"
        f"  words:   {n_words:,}\n"
        f"  ~tokens: {n_chars // 4:,} "
        f"(rough, chars/4 - real count comes from our tokenizer in Phase 2)",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
