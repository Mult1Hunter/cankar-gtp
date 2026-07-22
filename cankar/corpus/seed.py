"""Seed/refresh an author's works registry from Wikivir catalog pages.

Registry-first ingestion (ADR 0004): catalogs seed the registry BEFORE any
crawl; crawled shards mark works `ingested`. Idempotent; human `notes` are
never clobbered. Former scripts/corpus/build_registry.py (ADR 0007).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from cankar.corpus.catalog import parse_catalog
from cankar.corpus.registry import Registry, SourceRef
from cankar.corpus.wikivir import fetch_wikitext, make_session


def seed_registry(
    author: str,
    catalog_titles: list[str],
    registry_path: Path,
    shard: Path | None = None,
) -> dict[str, int]:
    reg = Registry.load(registry_path, author) if registry_path.exists() else Registry(author)
    n_before = len(reg.works)

    session = make_session()
    pages = fetch_wikitext(session, catalog_titles)
    missing = set(catalog_titles) - set(pages)
    if missing:
        raise SystemExit(f"catalog pages not found: {missing}")

    birth = death = None
    aliases_pending: list[tuple[str, str]] = []
    for title in catalog_titles:
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

    n_matched = n_added = 0
    if shard and shard.exists():
        for line in shard.read_text().splitlines():
            doc = json.loads(line)
            work = reg.find(doc["title"])
            if work is None:
                work = reg.upsert(doc["title"])
                n_added += 1
            else:
                n_matched += 1
            reg.add_source(
                work, SourceRef(source=doc["source"], id=doc["title"], status="ingested")
            )

    problems = reg.validate(
        min_year=(birth + 15) if birth else None,
        max_year=(death + 40) if death else None,
    )
    for p in problems:
        print(f"  VALIDATE: {p}", file=sys.stderr)

    reg.save(registry_path)
    print(
        f"registry {registry_path}: {n_before} -> {len(reg.works)} works "
        f"({author}, {birth}-{death}); shard matched {n_matched}, added {n_added}; "
        f"problems {len(problems)}",
        file=sys.stderr,
    )
    return {
        "works": len(reg.works),
        "matched": n_matched,
        "added": n_added,
        "problems": len(problems),
    }
