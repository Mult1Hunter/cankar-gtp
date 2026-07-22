"""Registry-first ingestion of configured PD authors - function calls, not
subprocesses (the subprocess chain was ADR 0007's exhibit A of scripts/ rot).

Sequence per author: PD gate -> seed registry from catalogs -> crawl (with
attribution roster) -> mark shard ingested -> coverage report -> validation.
"""

from __future__ import annotations

import sys
import tomllib
from datetime import UTC, datetime

from cankar.core.paths import authors_config, corpus_shard, coverage_report, works_registry
from cankar.corpus import seed, wikivir
from cankar.corpus.coverage import write_coverage
from cankar.corpus.registry import Registry

PD_YEARS = 70


def load_authors() -> list[dict]:
    return tomllib.loads(authors_config().read_text())["authors"]


def ingest_author(cfg: dict, roster: list[str]) -> None:
    name, slug = cfg["name"], cfg["slug"]
    cutoff = datetime.now(UTC).year - PD_YEARS
    if cfg["death_year"] > cutoff:
        raise SystemExit(
            f"PD GATE: {name} died {cfg['death_year']} > cutoff {cutoff} - not public domain"
        )

    registry_path = works_registry(slug)
    shard = corpus_shard(slug)

    seed.seed_registry(name, [cfg["index_page"]], registry_path)
    wikivir.crawl(
        categories=[cfg["category"]],
        author_pages=[cfg["index_page"]],
        out=shard,
        author_label=name,
        not_by=[other for other in roster if other != name],
    )
    seed.seed_registry(name, [cfg["index_page"]], registry_path, shard=shard)
    write_coverage(registry_path, name, coverage_report(slug))

    problems = Registry.load(registry_path, name).validate()
    if problems:
        for p in problems:
            print(f"PROBLEM: {p}", file=sys.stderr)
        raise SystemExit(f"registry validation failed for {name}")


def ingest(slugs: list[str] | None = None) -> None:
    """Ingest the given author slugs (None = all configured authors)."""
    authors = load_authors()
    roster = [a["name"] for a in authors]
    targets = authors if slugs is None else [a for a in authors if a["slug"] in slugs]
    unknown = set(slugs or []) - {a["slug"] for a in targets}
    if unknown:
        raise SystemExit(f"unknown author slugs: {sorted(unknown)}")
    for cfg in targets:
        print(f"\n=== {cfg['name']} ===", file=sys.stderr)
        ingest_author(cfg, roster)
