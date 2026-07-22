"""Corpus-stage CLI subcommands - the ONLY argparse holder for this stage.

Registered under the single `cankar` console entry (ADR 0007):
    cankar corpus crawl-wikivir --category "Kategorija:Ivan Cankar" ...
    cankar corpus ingest --all
    cankar corpus report --all
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from cankar.core.paths import (
    collisions_report,
    coverage_report,
    works_registries,
    works_registry,
)
from cankar.corpus import dlib, ingest, seed, wikipedia, wikivir
from cankar.corpus.coverage import cross_author_collisions, write_collisions, write_coverage
from cankar.corpus.registry import Registry


def _crawl_wikivir(args: argparse.Namespace) -> int:
    wikivir.crawl(
        categories=args.category,
        author_pages=args.author,
        out=args.out,
        author_label=args.author_label,
        source=args.source,
        min_chars=args.min_chars,
        expand=args.expand_subpages,
        expected_band=args.expected_band,
        not_by=args.not_by,
    )
    return 0


def _crawl_dlib(args: argparse.Namespace) -> int:
    dlib.crawl(
        query_contributor=args.query_contributor,
        author=args.author,
        registry_path=args.registry,
        out=args.out,
        triage=args.triage,
        min_alpha=args.min_alpha,
        min_chars=args.min_chars,
    )
    return 0


def _seed(args: argparse.Namespace) -> int:
    seed.seed_registry(args.author, args.catalog, args.registry, shard=args.shard)
    return 0


def _ingest(args: argparse.Namespace) -> int:
    ingest.ingest(None if args.all else [args.author_slug])
    return 0


def _ingest_wikipedia(args: argparse.Namespace) -> int:
    wikipedia.ingest(args.dump, args.out, min_chars=args.min_chars)
    return 0


def _validate(args: argparse.Namespace) -> int:
    problems: list[str] = []
    if args.registry:
        reg = Registry.load(args.registry, args.author)
        problems += reg.validate(min_year=args.min_year, max_year=args.max_year)
        print(f"{args.registry}: {len(reg.works)} works", file=sys.stderr)
    confirmations = cross_author_collisions(args.cross) if args.cross else []
    for c in confirmations:
        print(f"CONFIRM: {c}")
    for p in problems:
        print(f"PROBLEM: {p}")
    if problems or (confirmations and args.strict):
        return 1
    print(f"registry valid ({len(confirmations)} cross-author collisions to confirm)")
    return 0


def _report(args: argparse.Namespace) -> int:
    """Regenerate ALL reports deterministically (CI drift-checks the output)."""
    for cfg in ingest.load_authors():
        path = works_registry(cfg.slug)
        if path.exists():
            write_coverage(path, cfg.name, coverage_report(cfg.slug))
    n = write_collisions(works_registries(), collisions_report())
    print(f"reports regenerated; {n} cross-author collisions listed", file=sys.stderr)
    return 0


def register(parser: argparse.ArgumentParser) -> None:
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("crawl-wikivir", help="crawl Wikivir categories/author pages into a shard")
    p.add_argument("--category", action="append", default=[])
    p.add_argument("--author", action="append", default=[], help="author index page (ns-0)")
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--author-label", default=None)
    p.add_argument("--source", default="wikivir")
    p.add_argument("--min-chars", type=int, default=400)
    p.add_argument("--expand-subpages", action="store_true")
    p.add_argument("--expected-band", default=None)
    p.add_argument("--not-by", action="append", default=[])
    p.set_defaults(func=_crawl_wikivir)

    p = sub.add_parser("crawl-dlib", help="fill registry gaps from dLib.si (PD-marked only)")
    p.add_argument("--query-contributor", required=True)
    p.add_argument("--author", required=True)
    p.add_argument("--registry", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--triage", type=Path, default=None)
    p.add_argument("--min-alpha", type=float, default=0.84)
    p.add_argument("--min-chars", type=int, default=400)
    p.set_defaults(func=_crawl_dlib)

    p = sub.add_parser("seed", help="seed/refresh a works registry from catalog pages")
    p.add_argument("--author", required=True)
    p.add_argument("--catalog", action="append", required=True)
    p.add_argument("--registry", required=True, type=Path)
    p.add_argument("--shard", type=Path, default=None)
    p.set_defaults(func=_seed)

    p = sub.add_parser("ingest", help="registry-first ingestion of configured authors")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--author-slug")
    g.add_argument("--all", action="store_true")
    p.set_defaults(func=_ingest)

    p = sub.add_parser("ingest-wikipedia", help="ingest a slwiki dump as general-Slovene text")
    p.add_argument(
        "--dump", required=True, type=Path, help="path to slwiki-*-pages-articles.xml.bz2"
    )
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--min-chars", type=int, default=400)
    p.set_defaults(func=_ingest_wikipedia)

    p = sub.add_parser("validate", help="registry validation + cross-author collisions")
    p.add_argument("--registry", type=Path)
    p.add_argument("--author")
    p.add_argument("--min-year", type=int, default=None)
    p.add_argument("--max-year", type=int, default=None)
    p.add_argument("--cross", nargs="*", type=Path)
    p.add_argument("--strict", action="store_true")
    p.set_defaults(func=_validate)

    p = sub.add_parser("report", help="regenerate all coverage + collision reports")
    p.add_argument("--all", action="store_true", required=True)
    p.set_defaults(func=_report)
