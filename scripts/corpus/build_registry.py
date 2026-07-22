#!/usr/bin/env python3
"""Seed/refresh an author's works registry from Wikivir catalog pages.

The registry (registry/<slug>.jsonl) is the source of truth for known works
and where we got them - ADR 0004. Idempotent: re-runs merge; human `notes`
fields are never clobbered.

Usage:
    uv run scripts/build_registry.py \
        --author "Ivan Cankar" \
        --catalog "Ivan Cankar" \
        --catalog "Seznam del Ivana Cankarja" \
        --shard data/corpus/cankar.jsonl \
        --registry registry/cankar.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from cankar.corpus.catalog import parse_catalog
from cankar.corpus.registry import Registry, SourceRef, normalize_for_author
from cankar.corpus.wikisource import fetch_wikitext, make_session


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--author", required=True, help="canonical author name, e.g. 'Ivan Cankar'")
    ap.add_argument(
        "--catalog", action="append", required=True, help="Wikivir catalog page title (repeatable)"
    )
    ap.add_argument("--shard", type=Path, default=None, help="crawled shard: mark those ingested")
    ap.add_argument("--registry", required=True, type=Path, help="registry JSONL path")
    args = ap.parse_args()

    reg = (
        Registry.load(args.registry, args.author)
        if args.registry.exists()
        else Registry(args.author)
    )
    n_before = len(reg.works)

    session = make_session()
    pages = fetch_wikitext(session, args.catalog)
    missing = set(args.catalog) - set(pages)
    if missing:
        sys.exit(f"catalog pages not found: {missing}")

    birth = death = None
    aliases_pending: list[tuple[str, str]] = []
    for title in args.catalog:
        entries, meta = parse_catalog(pages[title])
        birth = birth or meta.birth_year
        death = death or meta.death_year
        for e in entries:
            if e.alias_of:
                aliases_pending.append((e.title, e.alias_of))
                continue
            reg.upsert(e.title, year=e.year, genre=e.genre, flags=e.flags)
    for alias, target in aliases_pending:
        work = reg.find(target)
        if work:
            reg.add_alias(work, alias)

    n_shard_matched = n_shard_unmatched = 0
    if args.shard and args.shard.exists():
        for line in args.shard.read_text().splitlines():
            doc = json.loads(line)
            work = reg.find(doc["title"])
            if work is None:
                # crawled page absent from catalogs - still a real work; add it
                work = reg.upsert(doc["title"])
                n_shard_unmatched += 1
            else:
                n_shard_matched += 1
            reg.add_source(
                work, SourceRef(source=doc["source"], id=doc["title"], status="ingested")
            )

    problems = reg.validate(
        min_year=(birth + 15) if birth else None,
        max_year=(death + 40) if death else None,
    )
    for p in problems:
        print(f"  VALIDATE: {p}", file=sys.stderr)

    reg.save(args.registry)
    print(
        f"registry {args.registry}: {n_before} -> {len(reg.works)} works "
        f"(author {args.author}, {birth}-{death})\n"
        f"  shard docs matched to catalog: {n_shard_matched}, "
        f"added from shard only: {n_shard_unmatched}\n"
        f"  validation problems: {len(problems)}",
        file=sys.stderr,
    )
    # normalized-title sanity for future cross-author collision checks
    _ = normalize_for_author  # imported for scripts that extend this


if __name__ == "__main__":
    main()
