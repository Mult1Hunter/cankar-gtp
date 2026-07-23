"""Seed/refresh an author's works registry from Wikivir catalog pages.

Registry-first ingestion (ADR 0004): catalogs seed the registry BEFORE any
crawl; crawled shards mark works `ingested`. Idempotent; human `notes` are
never clobbered. Former scripts/corpus/build_registry.py (ADR 0007).
"""

from __future__ import annotations

import logging
from pathlib import Path

from cankar.core.errors import CatalogPageMissingError
from cankar.corpus.catalog import parse_catalog
from cankar.corpus.registry import Registry, Source, SourceRef, SourceStatus
from cankar.corpus.shard import read_shard
from cankar.corpus.wikivir import fetch_wikitext, make_session

logger = logging.getLogger(__name__)


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
        raise CatalogPageMissingError(f"catalog pages not found: {sorted(missing)}")

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
        for doc in read_shard(shard):
            work = reg.find(doc["title"])
            if work is None:
                work = reg.upsert(doc["title"])
                n_added += 1
            else:
                n_matched += 1
            reg.add_source(
                work,
                SourceRef(
                    source=Source(doc["source"]), id=doc["title"], status=SourceStatus.INGESTED
                ),
            )

    problems = reg.validate(
        min_year=(birth + 15) if birth else None,
        max_year=(death + 40) if death else None,
    )
    for p in problems:
        logger.info(f"  VALIDATE: {p}")

    reg.save(registry_path)
    logger.info(
        f"registry {registry_path}: {n_before} -> {len(reg.works)} works "
        f"({author}, {birth}-{death}); shard matched {n_matched}, added {n_added}; "
        f"problems {len(problems)}"
    )
    return {
        "works": len(reg.works),
        "matched": n_matched,
        "added": n_added,
        "problems": len(problems),
    }
