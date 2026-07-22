#!/usr/bin/env python3
"""Registry-first ingestion of one (or all) PD authors from authors.toml.

Per author, runs the standard sequence (ADR 0004):
    seed registry from the Wikivir index page
    -> crawl category + index page into a shard
    -> re-seed (marks crawled docs `ingested`, absorbs shard-only works)
    -> coverage report
    -> validation
PD gate: refuses authors whose configured death_year is not 70+ years past.

Usage:
    uv run scripts/corpus/ingest_author.py --config configs/corpus/authors.toml --author tavcar
    uv run scripts/corpus/ingest_author.py --config configs/corpus/authors.toml --all
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tomllib
from datetime import UTC, datetime
from pathlib import Path

PD_YEARS = 70


def run(cmd: list[str]) -> None:
    print(f"+ {' '.join(cmd)}", file=sys.stderr)
    subprocess.run(cmd, check=True)


def ingest(author: dict, roster: list[str]) -> None:
    name, slug = author["name"], author["slug"]
    cutoff = datetime.now(UTC).year - PD_YEARS
    if author["death_year"] > cutoff:
        sys.exit(
            f"PD GATE: {name} died {author['death_year']} > cutoff {cutoff} - not public domain"
        )

    registry = f"registry/{slug}.jsonl"
    shard = f"data/corpus/{slug}.jsonl"
    seed = [
        "uv",
        "run",
        "scripts/corpus/build_registry.py",
        "--author",
        name,
        "--catalog",
        author["index_page"],
        "--registry",
        registry,
    ]
    run(seed)
    not_by = [x for other in roster if other != name for x in ("--not-by", other)]
    run(
        [
            "uv",
            "run",
            "scripts/corpus/crawl_wikivir.py",
            "--category",
            author["category"],
            "--author",
            author["index_page"],
            "--author-label",
            name,
            "--out",
            shard,
            *not_by,
        ]
    )
    run(seed + ["--shard", shard])
    run(
        [
            "uv",
            "run",
            "scripts/corpus/report_coverage.py",
            "--registry",
            registry,
            "--author",
            name,
            "--out",
            f"registry/coverage-{slug}.md",
        ]
    )
    run(
        [
            "uv",
            "run",
            "scripts/corpus/validate_registry.py",
            "--registry",
            registry,
            "--author",
            name,
        ]
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", required=True, type=Path)
    ap.add_argument("--author", help="slug from the config")
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()

    authors = tomllib.loads(args.config.read_text())["authors"]
    if args.all:
        targets = authors
    elif args.author:
        targets = [a for a in authors if a["slug"] == args.author]
        if not targets:
            sys.exit(f"unknown author slug {args.author!r}")
    else:
        sys.exit("need --author <slug> or --all")

    # attribution-guard roster: all configured authors + the primary author
    roster = [a["name"] for a in authors] + ["Ivan Cankar"]
    for author in targets:
        print(f"\n=== {author['name']} ===", file=sys.stderr)
        ingest(author, roster)


if __name__ == "__main__":
    main()
