#!/usr/bin/env python3
"""Validate a works registry - the collision/mismatch guard (ADR 0004).

Checks: work_id uniqueness/consistency, duplicate normalized titles within the
author, source publication years inside the plausible range, and (when several
registries exist) identical normalized titles across DIFFERENT authors, which
must be manually confirmed - generic titles collide.

Usage:
    uv run scripts/validate_registry.py --author "Ivan Cankar" \
        --registry registry/cankar.jsonl --min-year 1891 --max-year 1958
    uv run scripts/validate_registry.py --cross registry/*.jsonl
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

from cankar.corpus.registry import Registry, WorkRecord, normalize_title


def cross_author_collisions(paths: list[Path]) -> list[str]:
    by_norm: dict[str, list[str]] = defaultdict(list)
    for path in paths:
        for line in path.read_text().splitlines():
            if not line:
                continue
            w = WorkRecord.model_validate_json(line)
            by_norm[normalize_title(w.title)].append(f"{w.author}: {w.title} ({path.name})")
    return [
        f"title collision across authors - confirm these are different works: {entries}"
        for norm, entries in by_norm.items()
        if len({e.split(":")[0] for e in entries}) > 1
    ]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--registry", type=Path, help="single registry to validate")
    ap.add_argument("--author", help="author for --registry")
    ap.add_argument("--min-year", type=int, default=None)
    ap.add_argument("--max-year", type=int, default=None)
    ap.add_argument("--cross", nargs="*", type=Path, help="registries for cross-author check")
    ap.add_argument("--strict", action="store_true", help="cross collisions also fail the run")
    args = ap.parse_args()

    problems: list[str] = []
    if args.registry:
        if not args.author:
            ap.error("--registry requires --author")
        reg = Registry.load(args.registry, args.author)
        problems += reg.validate(min_year=args.min_year, max_year=args.max_year)
        print(f"{args.registry}: {len(reg.works)} works", file=sys.stderr)

    # cross-author title collisions are usually DIFFERENT works sharing a
    # generic title - they need human confirmation, not a red build
    confirmations = cross_author_collisions(args.cross) if args.cross else []
    for c in confirmations:
        print(f"CONFIRM: {c}")

    for p in problems:
        print(f"PROBLEM: {p}")
    if problems or (confirmations and args.strict):
        sys.exit(1)
    print(f"registry valid ({len(confirmations)} cross-author collisions to confirm)")


if __name__ == "__main__":
    main()
