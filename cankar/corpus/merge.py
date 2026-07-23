"""Merge stage - the final Phase 1 deliverable.

Folds the 18 shards into one quality-gated, deduplicated, deterministically
ordered corpus. Built to the architect critique of the merge brief:

- keep-preference is the SHARD, not doc["source"] (M1): both dLib shards carry
  source="dlib", all 15 literary shards carry "wikivir" - the tier and
  intra-tier order come from the filename, injected here.
- four dedup signals, not one (M3): exact content-hash, registry work-identity
  (same work_id across sources - the OCR-vs-clean Cankar dups MinHash misses),
  MinHash near-dup, and containment (measured, reported, not dropped - M4).
- cross-author near-dups never silently reattribute (M2): the committed
  collision_resolution.toml decides same_work attribution / protects distinct
  works; every cross-author drop appears in the report.
- two-pass streaming (S4): pass 1 decides drops, pass 2 writes in preference
  order - the 65M-word wikipedia shard is never materialized.

Quality gating applies to LITERARY shards only; Wikipedia stubs legitimately
score slovene_ratio 0.00 (quality_gate docstring).
"""

from __future__ import annotations

import logging
import tomllib
from collections import defaultdict
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import NamedTuple

from pydantic import BaseModel

from cankar.core.paths import works_registry
from cankar.core.reports import generated_marker, write_report
from cankar.core.schema import CorpusDoc
from cankar.corpus.dedup import CONTAINMENT_THRESHOLD, NearDupIndex, containment, shingles
from cankar.corpus.ingest import load_authors
from cankar.corpus.quality_gate import GateVerdict, gate
from cankar.corpus.registry import Registry, normalize_title
from cankar.corpus.shard import ShardWriter, content_hash, read_shard

logger = logging.getLogger(__name__)

WIKIPEDIA_SLUG = "wikipedia"  # the one non-literary shard - not quality-gated, lowest preference
# a containment "whole" must have at least this many unique 5-grams; ~ a few
# thousand words, the scale of a collected volume vs a single poem/sketch
CONTAINER_MIN_SHINGLES = 3000
# registry work-identity is CONFIRMED by content before dropping: normalize_for_author
# collapses year-disambiguated titles ('Črtice (Cankar 1914)' -> 'črtice'), so a bare
# work_id match can pair genuinely different collections. Measured 2026-07: true dups
# (Domov OCR-vs-clean 0.89, a story inside its collection 0.92) sit far above distinct
# same-id collections (the two Črtice, 0.00). 0.5 is the empty band between them.
REGISTRY_CONFIRM_CONTAINMENT = 0.5


def is_general_shard(slug: str) -> bool:
    """Wikipedia is general-reference (no author, no quality gate); everything
    else is authored literature."""
    return slug == WIKIPEDIA_SLUG


@dataclass(frozen=True)
class RootRecord:
    """The kept doc a duplicate was matched against (M2 attribution needs it)."""

    loc: tuple[str, int]
    author: str | None
    title: str


class LitDoc(NamedTuple):
    author: str
    title: str
    shingles: set[bytes]


class ResolutionKind(StrEnum):
    SAME_WORK = "same_work"  # one text in two shards - keep once, attribute as given
    DISTINCT = "distinct"  # different works sharing a title - keep all, protect


class CollisionResolution(BaseModel):
    """One [[collision]] entry, validated at load (ADR 0008)."""

    title: str
    resolution: ResolutionKind
    attribution: str | None = None
    note: str = ""


def load_resolutions(path: Path) -> dict[str, CollisionResolution]:
    raw = tomllib.loads(path.read_text()).get("collision", [])
    out: dict[str, CollisionResolution] = {}
    for entry in raw:
        res = CollisionResolution.model_validate(entry)
        out[normalize_title(res.title)] = res
    return out


def shard_tier(slug: str) -> int:
    """Keep-preference tier from the shard filename (M1). Lower wins. Patterns,
    not exact names, so a future dLib shard for another author is ranked, not
    silently promoted to top-preference literary."""
    if slug == WIKIPEDIA_SLUG:
        return 3
    if slug.startswith("dlib-") and slug.endswith("-gapfill"):
        return 2
    if slug.startswith("dlib-"):
        return 1
    return 0  # hand-transcribed Wikivir literary shards


def ordered_shards(corpus_dir: Path) -> list[Path]:
    """Shards in keep-preference order: (tier, slug). Deterministic."""
    return sorted(corpus_dir.glob("*.jsonl"), key=lambda p: (shard_tier(p.stem), p.stem))


def _author_registries() -> dict[str, Registry]:
    """author name -> its works Registry, for work-identity dedup (M3)."""
    regs: dict[str, Registry] = {}
    for cfg in load_authors():
        path = works_registry(cfg.slug)
        if path.exists():
            regs[cfg.name] = Registry.load(path, cfg.name)
    return regs


def _work_key(author: str | None, title: str, regs: dict[str, Registry]) -> tuple[str, str] | None:
    """(author, work_id) if the doc maps to a known work, else None. Same key
    across sources = same work (Wikivir 'Domov (Ivan Cankar)' and dLib 'Domov'
    both resolve to cankar work_id 'domov')."""
    if author is None:
        return None
    reg = regs.get(author)
    if reg is None:
        return None
    work = reg.find(title)
    return (author, work.work_id) if work else None


@dataclass
class MergeStats:
    kept: int = 0
    kept_words: int = 0
    skip_counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    cross_author: list[str] = field(default_factory=list)  # report lines
    registry_identity: list[str] = field(default_factory=list)  # dropped -> kept (auditability)
    registry_mismatch: list[str] = field(
        default_factory=list
    )  # same work_id, different text - kept
    containment: list[str] = field(default_factory=list)  # report lines
    reattributed: list[str] = field(default_factory=list)  # report lines
    conflicts: list[str] = field(default_factory=list)  # attribution overrides that disagreed


def merge(*, corpus_dir: Path, out: Path, resolution_path: Path, report_out: Path) -> MergeStats:
    resolutions = load_resolutions(resolution_path)
    regs = _author_registries()
    shards = ordered_shards(corpus_dir)
    stats = MergeStats()

    # --- pass 1: decide drops (keyed by (slug, line index), stable across passes) ---
    drop: dict[tuple[str, int], str] = {}
    reattribute: dict[tuple[str, int], str] = {}  # kept root loc -> new author
    hash_root: dict[str, str] = {}  # content hash -> kept root's meta key
    work_root: dict[tuple[str, str], str] = {}  # (author, work_id) -> kept root's meta key
    ndx = NearDupIndex()
    key_meta: dict[str, RootRecord] = {}
    lit_shingles: dict[str, LitDoc] = {}  # literary only (never wikipedia)
    counter = 0

    def drop_as_dup(
        loc: tuple[str, int], reason: str, root_key: str, author: str | None, title: str
    ) -> None:
        """Record a duplicate drop. registry_identity (same work_id, same author)
        is enumerated for audit; a cross-author drop consults the collision table
        so attribution is resolved for ANY signal - not just near-dup, since
        cross-author same-works are often byte-identical exact dups."""
        drop[loc] = reason
        stats.skip_counts[reason] += 1
        root = key_meta[root_key]
        if reason == "registry_identity":
            stats.registry_identity.append(f"- dropped {loc[0]}:{title!r} ~ kept {root.title!r}")
        if author == root.author:
            return
        stats.cross_author.append(
            f"- {reason}: dropped {loc[0]}:{title!r} ({author}) ~ kept "
            f"{root.loc[0]}:{root.title!r} ({root.author})"
        )
        res = resolutions.get(normalize_title(title))
        if res is not None and res.attribution:
            prior = reattribute.get(root.loc)
            if prior is not None and prior != res.attribution:
                stats.conflicts.append(f"- {root.title!r}: {prior!r} vs {res.attribution!r}")
            reattribute[root.loc] = res.attribution
            stats.reattributed.append(f"- {root.title!r} -> {res.attribution} ({res.note})")

    for path in shards:
        slug = path.stem
        literary = not is_general_shard(slug)
        for idx, doc in enumerate(read_shard(path)):
            loc = (slug, idx)
            text, title, author = doc["text"], doc["title"], doc.get("author")

            if literary:
                verdict = gate(text)
                if verdict != GateVerdict.KEPT:
                    drop[loc] = f"gate_{verdict}"
                    stats.skip_counts[f"gate_{verdict}"] += 1
                    continue

            key = f"{counter:09d}"
            counter += 1

            h = content_hash(text)
            if h in hash_root:
                drop_as_dup(loc, "exact_dup", hash_root[h], author, title)
                continue

            sh = shingles(text) if literary else None  # reused by registry-confirm + containment
            wk = _work_key(author, title, regs)
            if wk is not None and wk in work_root and sh is not None:
                root_sh = lit_shingles[work_root[wk]].shingles
                if max(containment(sh, root_sh), containment(root_sh, sh)) >= (
                    REGISTRY_CONFIRM_CONTAINMENT
                ):
                    drop_as_dup(loc, "registry_identity", work_root[wk], author, title)
                    continue
                # same work_id but different text - a normalize_for_author over-collapse;
                # keep both and surface for registry cleanup (never silent text loss)
                stats.registry_mismatch.append(
                    f"- {title!r} shares work_id with {key_meta[work_root[wk]].title!r} "
                    "but content differs - kept both"
                )

            root = ndx.add_or_match(key, text)
            if root is not None:
                res = resolutions.get(normalize_title(title))
                distinct_cross = (
                    author != key_meta[root].author
                    and res is not None
                    and res.resolution is ResolutionKind.DISTINCT
                )
                if distinct_cross:
                    ndx.insert(key, text)  # false positive on distinct works - keep it
                else:
                    drop_as_dup(loc, "near_dup", root, author, title)
                    continue

            # KEPT
            hash_root[h] = key
            if wk is not None:
                work_root[wk] = key
            key_meta[key] = RootRecord(loc=loc, author=author, title=title)
            if sh is not None:
                lit_shingles[key] = LitDoc(author or "?", title, sh)

    _measure_containment(lit_shingles, stats)

    # --- pass 2: write in preference order, applying re-attribution ---
    args: dict[str, object] = {
        "shards": [p.stem for p in shards],
        "resolution": resolution_path.name,
    }
    writer = ShardWriter(out, source="merged", script="cankar corpus merge", args=args)
    with writer:
        for path in shards:
            slug = path.stem
            for idx, doc in enumerate(read_shard(path)):
                loc = (slug, idx)
                if loc in drop:
                    continue
                author = reattribute.get(loc, doc.get("author"))
                writer.write(
                    CorpusDoc(
                        title=doc["title"],
                        url=doc["url"],
                        text=doc["text"],
                        n_chars=len(doc["text"]),
                        source=doc["source"],
                        author=author,
                    )
                )
        writer.skip_counts = dict(stats.skip_counts)
    stats.kept, stats.kept_words = writer.n_docs, writer.n_words

    write_merge_report(stats, report_out)
    logger.info(f"merged {out}: {stats.kept} docs, {stats.kept_words:,} words")
    for reason, n in sorted(stats.skip_counts.items()):
        logger.info(f"  dropped {reason}: {n}")
    return stats


def _measure_containment(lit_shingles: dict[str, LitDoc], stats: MergeStats) -> None:
    """Report (do not drop) kept literary docs contained in a larger same-author
    doc - the collected-volume subpart class MinHash misses (M4)."""
    by_author: dict[str, list[LitDoc]] = defaultdict(list)
    for lit in lit_shingles.values():
        by_author[lit.author].append(lit)
    for docs in by_author.values():
        containers = [d for d in docs if len(d.shingles) >= CONTAINER_MIN_SHINGLES]
        for d in docs:
            for c in containers:
                if (
                    c.title != d.title
                    and len(c.shingles) > len(d.shingles)
                    and containment(d.shingles, c.shingles) > CONTAINMENT_THRESHOLD
                ):
                    stats.containment.append(f"- {d.title!r} contained in {c.title!r}")
                    break


def write_merge_report(stats: MergeStats, out: Path) -> None:
    lines = [
        generated_marker("cankar corpus merge", snapshot=True),
        "# Merge report",
        "",
        f"**{stats.kept:,} docs / {stats.kept_words:,} words** in the merged corpus.",
        "",
        "## Drops by reason",
        "",
        "| reason | docs |",
        "|---|--:|",
    ]
    lines += [f"| {r} | {n:,} |" for r, n in sorted(stats.skip_counts.items())]
    for heading, rows in (
        ("Attribution conflicts (collision table disagreed - REVIEW)", stats.conflicts),
        ("Re-attributions (collision table)", stats.reattributed),
        ("Cross-author dedup drops", stats.cross_author),
        ("Registry-identity drops (same work_id, content-confirmed)", stats.registry_identity),
        (
            "Registry-identity mismatches (same work_id, DIFFERENT text - kept both)",
            stats.registry_mismatch,
        ),
        ("Containment (reported, not dropped)", stats.containment),
    ):
        lines += ["", f"## {heading}", ""]
        lines += rows or ["- none"]
    write_report(out, lines)
