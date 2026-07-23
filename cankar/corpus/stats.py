"""Statistical corpus-quality metrics - measuring the training signal, not just
the pipeline (the gap an external review correctly flagged).

Golden/structure tests prove the pipeline is well-built; these metrics prove the
corpus is good for training a language model. Grounded in LLM-pretraining
practice (FineWeb, Gopher, n-gram novelty): duplication, lexical diversity
(length-invariant MATTR), duplicate-line fraction, unknown-character rate, and
residual-markup rate are the signals that predict whether tokens are worth
training on - especially for a small model, where noise and near-duplicates
bite harder. Near-duplicate detection lives in cankar.corpus.dedup.

Pure, streaming, dependency-light (no numpy); testable on synthetic inputs so
the metrics themselves are proven to flag garbage.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from statistics import median

from cankar.core.metrics import percentile
from cankar.core.reports import generated_marker, write_report
from cankar.corpus.shard import content_hash

# Slovene letters + ASCII, digits, whitespace, and ordinary literary punctuation.
# Characters outside this set are the OCR-garbage / foreign-script signal.
_ALLOWED = set(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "čšžćđČŠŽĆĐ"
    "áàâäéèêëíìîïóòôöúùûüýőűÁÀÂÄÉÈÊËÍÌÎÏÓÒÔÖÚÙÛÜ"  # accents in loanwords/names
    "0123456789"
    " \t\n\r"
    ".,;:!?-–—…\"'»«„“”()[]/*"
)
# markup that should NOT survive cleaning - each is a residual-dirt probe
_MARKUP_PROBES = {
    "wikitable": re.compile(r"\{\|"),
    "wikilink": re.compile(r"\[\["),
    "template": re.compile(r"\{\{"),
    "image_frag": re.compile(r"\b(thumb|sličica)\|"),
    "ref_tag": re.compile(r"<ref"),
    "heading": re.compile(r"^==+.+==+\s*$", re.MULTILINE),
}


@dataclass
class ShardMetrics:
    """Quality metrics for one shard (ADR 0008: typed result)."""

    name: str
    n_docs: int = 0
    n_words: int = 0
    n_chars: int = 0
    words_min: int = 0
    words_median: float = 0.0
    words_p95: int = 0
    words_max: int = 0
    mattr: float = 0.0  # moving-average type-token ratio (window 500) - LENGTH-INVARIANT
    dup_line_frac: float = 0.0  # mean fraction of duplicate lines per doc (Gopher-style)
    unknown_char_rate: float = 0.0  # fraction of chars outside the Slovene set
    exact_dup_rate: float = 0.0  # fraction of docs sharing a content hash
    markup_doc_rate: dict[str, float] = field(default_factory=dict)  # per-probe doc fraction


MATTR_WINDOW = 500  # Covington & McFall (2010) moving-average TTR window


def mattr(words: list[str], window: int = MATTR_WINDOW) -> float:
    """Moving-average type-token ratio: mean unique/total over sliding windows.
    Length-invariant above the window, unlike raw TTR (which falls as corpus
    size grows because vocabulary saturates). Caveat (design-review): docs
    SHORTER than the window get raw whole-doc TTR, which is upward-biased -
    cross-shard comparisons partially reflect doc-length mixture for shards
    whose median doc is under the window (wikipedia ~232, kette ~117 words)."""
    if len(words) <= window:
        return len(set(w.casefold() for w in words)) / len(words) if words else 0.0
    total = 0.0
    n = len(words) - window + 1
    for i in range(0, n, max(1, window // 5)):  # stride for speed on 65M words
        win = words[i : i + window]
        total += len({w.casefold() for w in win}) / window
    return total / len(range(0, n, max(1, window // 5)))


def dup_line_frac(text: str) -> float:
    """Gopher-style: fraction of lines that duplicate an earlier line. Catches
    templated/list/boilerplate garbage; length-robust (unlike char-trigram rep,
    which saturates with length regardless of quality)."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if len(lines) < 2:
        return 0.0
    seen: set[str] = set()
    dup = 0
    for ln in lines:
        if ln in seen:
            dup += 1
        seen.add(ln)
    return dup / len(lines)


def compute_metrics(name: str, docs: Iterable[dict]) -> ShardMetrics:
    """One streaming pass over a shard's docs, computing every metric."""
    m = ShardMetrics(name=name)
    word_counts: list[int] = []
    hashes: set[str] = set()
    n_dup = 0
    unknown = 0
    mattr_weighted = 0.0
    dupline_weighted = 0.0
    markup_hits = dict.fromkeys(_MARKUP_PROBES, 0)

    for d in docs:
        text = d["text"]
        words = text.split()
        m.n_docs += 1
        m.n_words += len(words)
        m.n_chars += len(text)
        word_counts.append(len(words))

        h = content_hash(text)
        if h in hashes:
            n_dup += 1
        hashes.add(h)

        unknown += sum(1 for ch in text if not ch.isspace() and ch not in _ALLOWED)
        mattr_weighted += mattr(words) * len(words)  # word-weighted corpus MATTR
        dupline_weighted += dup_line_frac(text) * len(words)
        for probe, rx in _MARKUP_PROBES.items():
            if rx.search(text):
                markup_hits[probe] += 1

    if m.n_docs:
        sw = sorted(word_counts)
        m.words_min = sw[0]
        m.words_median = median(sw)
        m.words_p95 = int(percentile(sw, 0.95))
        m.words_max = sw[-1]
        m.mattr = round(mattr_weighted / m.n_words, 5) if m.n_words else 0.0
        m.dup_line_frac = round(dupline_weighted / m.n_words, 5) if m.n_words else 0.0
        m.unknown_char_rate = round(unknown / m.n_chars, 6) if m.n_chars else 0.0
        m.exact_dup_rate = round(n_dup / m.n_docs, 5)
        m.markup_doc_rate = {k: round(v / m.n_docs, 5) for k, v in markup_hits.items()}
    return m


def write_quality_report(metrics: list[ShardMetrics], out: Path) -> None:
    """Committed quality snapshot. Not CI-drift-checked (computed from gitignored
    data/); regenerate with `cankar corpus stats`. This is the evidence that the
    corpus - not just the pipeline - is measured."""
    total_docs = sum(m.n_docs for m in metrics)
    total_words = sum(m.n_words for m in metrics)
    lines = [
        generated_marker("cankar corpus stats", snapshot=True),
        "# Corpus quality metrics",
        "",
        "Length-invariant statistical signals of training quality (MATTR, "
        "duplicate-line fraction, unknown-char rate, residual markup). Snapshot; "
        "regenerate with `cankar corpus stats`.",
        "",
        f"**{total_docs:,} docs, {total_words:,} words** across {len(metrics)} shards.",
        "",
        "| shard | docs | words | MATTR | dup-line | unknown% | exact-dup% "
        "| med words | p95 words |",
        "|---|--:|--:|--:|--:|--:|--:|--:|--:|",
    ]
    for m in sorted(metrics, key=lambda x: x.name):
        lines.append(
            f"| {m.name} | {m.n_docs:,} | {m.n_words:,} | {m.mattr:.3f} | "
            f"{m.dup_line_frac:.3f} | {m.unknown_char_rate * 100:.3f}% | "
            f"{m.exact_dup_rate * 100:.2f}% | "
            f"{int(m.words_median)} | {m.words_p95:,} |"
        )
    dirty = {
        f"{m.name}:{probe}={rate * 100:.2f}%"
        for m in metrics
        for probe, rate in m.markup_doc_rate.items()
        if rate > 0
    }
    lines += [
        "",
        "## Residual markup probes",
        "",
        (
            "All probes 0.000% in every shard."
            if not dirty
            else "Nonzero probe hits (doc fraction): " + ", ".join(sorted(dirty)) + "."
        ),
    ]
    lines += [
        "",
        "## Reading the numbers",
        "- **MATTR** (moving-average type-token ratio, window 500): lexical "
        "diversity, length-invariant above the window. Caveat: docs shorter "
        "than 500 words contribute raw TTR (upward-biased), so cross-shard "
        "comparison is soft where the median doc is short. Uniform ~0.6-0.7 = "
        "consistent clean prose; an anomalously low shard would signal "
        "boilerplate.",
        "- **dup-line**: mean fraction of duplicate lines per doc (Gopher-style); "
        "high = templated/list garbage.",
        "- **unknown%**: chars outside the Slovene+Latin+punctuation set; the "
        "OCR-garbage / foreign-script signal.",
    ]
    write_report(out, lines)
