"""Near-duplicate detection via MinHash LSH.

Exact-hash dedup (cankar.corpus.stats.exact_dup_rate) finds byte-identical docs;
this finds NEAR duplicates - edition variants, reworded geo-stubs, the same work
transcribed twice - which exact hashing misses and which matter disproportionately
for a small model (repeated near-dups overfit it). Parameters follow FineWeb
practice: MinHash over word 5-grams, ~0.75 Jaccard threshold, 128 permutations.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from datasketch import MinHash, MinHashLSH

# shingles/containment/SHINGLE/CONTAINMENT_THRESHOLD promoted to core.textsim
# (second consumer: evals holdout-closure); re-exported here for merge + the
# report command that already import them from dedup.
from cankar.core.reports import generated_marker, write_report
from cankar.core.textsim import CONTAINMENT_THRESHOLD, SHINGLE, containment, shingles

__all__ = ["CONTAINMENT_THRESHOLD", "SHINGLE", "containment", "shingles"]

NUM_PERM = 128
SEED = 1  # pin MinHash permutations for reproducible drops (design-review S3)
# 0.75 Jaccard follows FineWeb. Calibration rule (ADR 0006): the merge stage
# DROPS docs at this threshold, so real labeled pairs are committed as fixtures.
THRESHOLD = 0.75


def minhash(text: str) -> MinHash:
    m = MinHash(num_perm=NUM_PERM, seed=SEED)
    m.update_batch(list(shingles(text)))
    return m


class NearDupIndex:
    """Incremental MinHash-LSH index: add docs in keep-preference order; each
    add either inserts (novel) or reports the root key it duplicates. The one
    near-dup primitive both the report command and the merge stage use."""

    def __init__(self, threshold: float = THRESHOLD):
        self._lsh = MinHashLSH(threshold=threshold, num_perm=NUM_PERM)

    def add_or_match(self, key: str, text: str) -> str | None:
        """Insert `key` if novel and return None; else return the earliest
        already-inserted key it near-duplicates (keep-first semantics).

        Keys MUST sort lexicographically by insertion order (zero-padded
        counters, or a fixed-width preference prefix) so `min` picks the root
        the caller would keep."""
        mh = minhash(text)
        matches = self._lsh.query(mh)
        if matches:
            return min(matches)
        self._lsh.insert(key, mh)
        return None

    def insert(self, key: str, text: str) -> None:
        """Force-insert regardless of matches - for keeping a doc the caller has
        decided is NOT a duplicate (e.g. a collision-table 'distinct' pair that
        MinHash flagged as a false positive)."""
        self._lsh.insert(key, minhash(text))


@dataclass
class DedupResult:
    n_docs: int
    n_duplicate_docs: int  # docs that are a near-dup of an earlier-kept doc
    n_clusters: int  # distinct roots that absorbed >=1 duplicate
    duplicate_rate: float


def find_near_duplicates(
    docs: Iterable[dict], threshold: float = THRESHOLD
) -> tuple[DedupResult, list[int]]:
    """Greedy near-dup pass for the report command. Keep-preference IS the input
    ordering (the merge sorts by source preference before calling equivalents)."""
    index = NearDupIndex(threshold)
    drop: list[int] = []
    kept = 0
    roots: set[str] = set()
    for i, d in enumerate(docs):
        root = index.add_or_match(f"{i:012d}", d["text"])
        if root is not None:
            drop.append(i)
            roots.add(root)
        else:
            kept += 1
    n = kept + len(drop)
    result = DedupResult(
        n_docs=n,
        n_duplicate_docs=len(drop),
        n_clusters=len(roots),
        duplicate_rate=round(len(drop) / n, 5) if n else 0.0,
    )
    return result, drop


def write_dedup_report(named_results: dict[str, DedupResult], out: Path) -> None:
    """Committed near-duplicate snapshot (regenerate with `cankar corpus dedup`).
    Not CI-drift-checked - computed from gitignored data/."""
    lines = [
        generated_marker("cankar corpus dedup", snapshot=True),
        "# Near-duplicate report (MinHash LSH, word 5-grams, 0.75 Jaccard)",
        "",
        "Near-dups exact hashing misses: edition variants, OCR-vs-transcription,",
        "reworded stubs. Feeds the merge stage (keep by source preference).",
        "",
        "| group | docs | near-dup docs | clusters | rate |",
        "|---|--:|--:|--:|--:|",
    ]
    for name, r in named_results.items():
        lines.append(
            f"| {name} | {r.n_docs:,} | {r.n_duplicate_docs:,} | "
            f"{r.n_clusters:,} | {r.duplicate_rate * 100:.2f}% |"
        )
    write_report(out, lines)
