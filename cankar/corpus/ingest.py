"""Registry-first ingestion of configured PD authors - function calls, not
subprocesses (the subprocess chain was ADR 0007's exhibit A of scripts/ rot).

Sequence per author: PD gate -> seed registry from catalogs -> crawl (with
attribution roster) -> mark shard ingested -> coverage report -> validation.
"""

from __future__ import annotations

import logging
import tomllib
from datetime import UTC, datetime

from pydantic import BaseModel

from cankar.core.errors import PdGateError, RegistryValidationError, UnknownAuthorError
from cankar.core.paths import authors_config, corpus_shard, coverage_report, works_registry
from cankar.corpus import seed, wikivir
from cankar.corpus.coverage import write_coverage
from cankar.corpus.registry import Registry

logger = logging.getLogger(__name__)


class AuthorConfig(BaseModel):
    """One [[authors]] entry in configs/corpus/authors.toml, validated at load."""

    name: str
    slug: str
    category: str
    index_page: str
    death_year: int
    category_pages: int


PD_YEARS = 70


def load_authors() -> list[AuthorConfig]:
    raw = tomllib.loads(authors_config().read_text())["authors"]
    return [AuthorConfig.model_validate(entry) for entry in raw]


def ingest_author(cfg: AuthorConfig, roster: list[str]) -> None:
    name, slug = cfg.name, cfg.slug
    cutoff = datetime.now(UTC).year - PD_YEARS
    if cfg.death_year > cutoff:
        raise PdGateError(f"{name} died {cfg.death_year} > cutoff {cutoff}")

    registry_path = works_registry(slug)
    shard = corpus_shard(slug)

    seed.seed_registry(name, [cfg.index_page], registry_path)
    wikivir.crawl(
        categories=[cfg.category],
        author_pages=[cfg.index_page],
        out=shard,
        author_label=name,
        not_by=[other for other in roster if other != name],
    )
    seed.seed_registry(name, [cfg.index_page], registry_path, shard=shard)
    write_coverage(registry_path, name, coverage_report(slug))

    problems = Registry.load(registry_path, name).validate()
    if problems:
        raise RegistryValidationError(name, problems)


def ingest(slugs: list[str] | None = None) -> None:
    """Ingest the given author slugs (None = all configured authors)."""
    authors = load_authors()
    roster = [a.name for a in authors]
    targets = authors if slugs is None else [a for a in authors if a.slug in slugs]
    unknown = set(slugs or []) - {a.slug for a in targets}
    if unknown:
        raise UnknownAuthorError(f"unknown author slugs: {sorted(unknown)}")
    for cfg in targets:
        logger.info(f"=== {cfg.name} ===")
        ingest_author(cfg, roster)
