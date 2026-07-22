"""Near-duplicate detection via MinHash LSH.

Exact-hash dedup (cankar.corpus.stats.exact_dup_rate) finds byte-identical docs;
this finds NEAR duplicates - edition variants, reworded geo-stubs, the same work
transcribed twice - which exact hashing misses and which matter disproportionately
for a small model (repeated near-dups overfit it). Parameters follow FineWeb
practice: MinHash over word 5-grams, ~0.75 Jaccard threshold, 128 permutations.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from datasketch import MinHash, MinHashLSH

NUM_PERM = 128
THRESHOLD = 0.75
SHINGLE = 5  # word n-gram size

_WORD_RE = re.compile(r"\w+", re.UNICODE)


def _shingles(text: str, k: int = SHINGLE) -> set[bytes]:
    words = _WORD_RE.findall(text.casefold())
    if len(words) < k:
        return {" ".join(words).encode()} if words else set()
    return {" ".join(words[i : i + k]).encode() for i in range(len(words) - k + 1)}


def _minhash(text: str) -> MinHash:
    m = MinHash(num_perm=NUM_PERM)
    m.update_batch(list(_shingles(text)))
    return m


@dataclass
class DedupResult:
    n_docs: int
    n_duplicate_docs: int  # docs that are a near-dup of an earlier-kept doc
    n_clusters: int  # groups of mutually near-duplicate docs
    duplicate_rate: float

    def as_dict(self) -> dict[str, float]:
        return dict(vars(self))


def find_near_duplicates(
    docs: Iterable[dict], threshold: float = THRESHOLD
) -> tuple[DedupResult, list[int]]:
    """Greedy near-dup pass: docs in insertion order; each doc that matches an
    already-kept doc is marked duplicate. Returns the result summary and the
    indices to DROP (keeping the first of each near-dup group)."""
    lsh = MinHashLSH(threshold=threshold, num_perm=NUM_PERM)
    drop: list[int] = []
    kept = 0
    clusters = 0
    seen_cluster: set[str] = set()
    for i, d in enumerate(docs):
        mh = _minhash(d["text"])
        matches = lsh.query(mh)
        if matches:
            drop.append(i)
            root = min(matches)
            if root not in seen_cluster:
                clusters += 1
                seen_cluster.add(root)
        else:
            lsh.insert(str(i), mh)
            kept += 1
    n = kept + len(drop)
    result = DedupResult(
        n_docs=n,
        n_duplicate_docs=len(drop),
        n_clusters=clusters,
        duplicate_rate=round(len(drop) / n, 5) if n else 0.0,
    )
    return result, drop
