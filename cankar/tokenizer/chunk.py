"""Chunk the merged corpus into training documents <= budget tokens (ADR 0012).

nanochat's BOS-bestfit dataloader packs whole documents into rows of
row_capacity = T+1 and DISCARDS the tail of any document it must crop; 55%
of the Cankar slice exceeds T=2048 and would lose ~96-99% of its tokens
unchunked. Chunking removes the loader's failure premise instead of forking
the loader (architect critique A-1).

Invariants (critique MF-1..MF-4):
- pieces retain their trailing separators, so a doc's chunks concatenate
  byte-exact to the original text - no separator bookkeeping, paragraph
  breaks stay in the training distribution;
- the split ladder (paragraph -> line -> sentence -> hard) recurses per
  over-budget PIECE, not per doc - a structured doc with one 8k-token
  paragraph keeps its other paragraphs paragraph-grained;
- hard splits snap to valid char boundaries (strict decode with back-off)
  and every emitted chunk is re-encoded and verified <= budget, because
  re-tokenization of substrings is not count-preserving under regex BPE;
- budget means encode_ordinary count EXCLUDING BOS: the loader prepends
  BOS and row_capacity = T+1 absorbs exactly that. A 2048-token chunk
  fits a row; a 2049-token chunk never does.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from enum import IntEnum
from pathlib import Path

import tiktoken
from pydantic import BaseModel

from cankar.core.errors import CankarError
from cankar.core.jsonl import iter_jsonl_docs
from cankar.core.metrics import percentile
from cankar.core.reports import generated_marker, write_report
from cankar.core.schema import ChunkDoc

log = logging.getLogger("cankar.tokenizer")

LADDER_VERSION = 2  # v2: seam-overflow counter, enum ladder (same split policy)
DEFAULT_BUDGET = 2048  # == Phase 3 max_seq_len; re-chunk if that changes (ADR 0012)
_SENTENCE_SPLIT = re.compile(r"([.!?…]\s+)")


class ChunkLevel(IntEnum):
    """Split ladder, coarse to fine; ordinal - the ladder descends by +1."""

    PASS_THROUGH = -1
    PARAGRAPH = 0
    LINE = 1
    SENTENCE = 2
    HARD = 3

    @property
    def label(self) -> str:
        return self.name.lower().replace("_", "-")


class ChunkRunStats(BaseModel):
    n_docs: int = 0
    n_docs_split: int = 0
    n_chunks: int = 0
    n_tokens_total: int = 0
    # seam overflows: chunks the pack-verify pass had to hard-split because
    # re-tokenization across piece seams exceeded the budget (design-review
    # 2026-07: these are invisible to the ladder counts and must be counted)
    seam_hard_splits: int = 0
    # source -> deepest-level-label -> doc count (calibration + drift signal)
    ladder_by_source: dict[str, dict[str, int]] = {}
    chunk_token_lengths: list[int] = []


class ChunksManifest(BaseModel):
    """Committed provenance for the chunks artifact (ADR 0003, critique MF-7):
    without the tokenizer hash, every n_tokens in chunks.jsonl is unverifiable."""

    schema_version: int = 1
    budget: int
    ladder_version: int
    tokenizer_name: str
    tokenizer_pkl_sha256: str
    corpus_sha256: str
    n_docs: int
    n_docs_split: int
    n_chunks: int
    n_tokens_total: int
    seam_hard_splits: int
    ladder_by_source: dict[str, dict[str, int]]
    chunks_sha256: str
    git_sha: str
    created_at: str


def _split_keep_separators(text: str, level: ChunkLevel) -> list[str]:
    """Split one level down; ''.join(result) == text always."""
    if level is ChunkLevel.PARAGRAPH:
        parts = text.split("\n\n")
        return [p + "\n\n" for p in parts[:-1]] + [parts[-1]]
    if level is ChunkLevel.LINE:
        parts = text.split("\n")
        return [p + "\n" for p in parts[:-1]] + [parts[-1]]
    if level is ChunkLevel.SENTENCE:
        raw = _SENTENCE_SPLIT.split(text)
        pieces = []
        for i in range(0, len(raw) - 1, 2):
            pieces.append(raw[i] + raw[i + 1])
        if raw[-1]:
            pieces.append(raw[-1])
        return pieces
    raise CankarError(f"no separator split at level {level.label}")


def _hard_split_head(text: str, enc: tiktoken.Encoding, budget: int) -> str:
    """First <= budget tokens of text, snapped to a valid char boundary and
    verified by re-encoding (critique MF-3)."""
    ids = enc.encode_ordinary(text)
    cut = budget
    while cut > 0:
        head_bytes = b"".join(enc.decode_single_token_bytes(t) for t in ids[:cut])
        try:
            head = head_bytes.decode("utf-8")
        except UnicodeDecodeError:
            cut -= 1
            continue
        if len(enc.encode_ordinary(head)) <= budget:
            return head
        cut -= 1
    raise CankarError("hard split could not produce a non-empty head (budget too small?)")


def _hard_pieces(text: str, enc: tiktoken.Encoding, budget: int) -> list[str]:
    """Iterative last-rung split (no recursion depth on pathological docs)."""
    pieces: list[str] = []
    rest = text
    while len(enc.encode_ordinary(rest)) > budget:
        head = _hard_split_head(rest, enc, budget)
        pieces.append(head)
        rest = rest[len(head) :]
    pieces.append(rest)
    return pieces


def _atomic_pieces(
    text: str, enc: tiktoken.Encoding, budget: int, level: ChunkLevel
) -> tuple[list[str], ChunkLevel]:
    """Recursive ladder: (pieces each <= budget tokens joining to text,
    deepest level used - PASS_THROUGH when no split was needed)."""
    if len(enc.encode_ordinary(text)) <= budget:
        return [text], ChunkLevel.PASS_THROUGH
    if level is ChunkLevel.HARD:
        return _hard_pieces(text, enc, budget), ChunkLevel.HARD
    pieces = _split_keep_separators(text, level)
    if len(pieces) == 1:
        return _atomic_pieces(text, enc, budget, ChunkLevel(level + 1))
    deepest: ChunkLevel = level
    out: list[str] = []
    for piece in pieces:
        sub, sub_deepest = _atomic_pieces(piece, enc, budget, ChunkLevel(level + 1))
        out.extend(sub)
        deepest = max(deepest, sub_deepest)
    return out, ChunkLevel(deepest)


def _pack(
    pieces: list[str], enc: tiktoken.Encoding, budget: int
) -> tuple[list[tuple[str, int]], int]:
    """Greedy-pack adjacent pieces into (chunk text, verified n_tokens) pairs.
    Every chunk's count comes from re-encoding its joined text - piece-sum
    arithmetic is not exact under regex BPE. Returns (chunks, seam overflows
    the verify pass had to hard-split)."""
    counts = [len(enc.encode_ordinary(p)) for p in pieces]
    joined: list[str] = []
    current: list[str] = []
    current_sum = 0
    for piece, n in zip(pieces, counts, strict=True):
        if current and current_sum + n > budget:
            joined.append("".join(current))
            current, current_sum = [piece], n
        else:
            current.append(piece)
            current_sum += n
    if current:
        joined.append("".join(current))
    verified: list[tuple[str, int]] = []
    seam_hard = 0
    i = 0
    while i < len(joined):
        chunk = joined[i]
        n = len(enc.encode_ordinary(chunk))
        if n <= budget:
            verified.append((chunk, n))
            i += 1
        else:
            seam_hard += 1
            head = _hard_split_head(chunk, enc, budget)
            verified.append((head, len(enc.encode_ordinary(head))))
            joined[i] = chunk[len(head) :]
    return verified, seam_hard


def chunk_text(
    text: str, enc: tiktoken.Encoding, budget: int
) -> tuple[list[tuple[str, int]], ChunkLevel, int]:
    """Chunk one document -> ((text, n_tokens) pairs, deepest ladder level,
    seam-overflow count)."""
    n = len(enc.encode_ordinary(text))
    if n <= budget:
        return [(text, n)], ChunkLevel.PASS_THROUGH, 0
    pieces, deepest = _atomic_pieces(text, enc, budget, ChunkLevel.PARAGRAPH)
    packed, seam_hard = _pack(pieces, enc, budget)
    return packed, deepest, seam_hard


def chunk_corpus(
    corpus_path: Path, enc: tiktoken.Encoding, budget: int
) -> Iterator[tuple[list[ChunkDoc], ChunkLevel, int]]:
    """Yield (chunks, deepest_level, seam_overflows) per doc, with
    reconstruction, span, and url-uniqueness invariants enforced.
    Eager wrapper: the missing-corpus error must fire before run_chunking
    opens its output file (design-review 2026-07)."""
    docs = iter_jsonl_docs(corpus_path, missing_hint="run: cankar corpus merge")
    return _chunk_docs(docs, enc, budget)


def _chunk_docs(
    docs: Iterator[dict], enc: tiktoken.Encoding, budget: int
) -> Iterator[tuple[list[ChunkDoc], ChunkLevel, int]]:
    seen_urls: set[str] = set()
    for doc in docs:
        url, text = doc["url"], doc["text"]
        if url in seen_urls:
            raise CankarError(f"duplicate url in merged corpus (holdout key breaks): {url}")
        seen_urls.add(url)
        pairs, level, seam_hard = chunk_text(text, enc, budget)
        if "".join(t for t, _ in pairs) != text:
            raise CankarError(f"reconstruction failed for {url} - chunking bug, aborting")
        chunks = []
        pos = 0
        for i, (t, n_tokens) in enumerate(pairs):
            if n_tokens > budget:
                raise CankarError(f"over-budget chunk ({n_tokens} > {budget}) for {url}")
            chunks.append(
                ChunkDoc(
                    title=doc["title"],
                    url=url,
                    text=t,
                    n_chars=len(t),
                    n_tokens=n_tokens,
                    source=doc["source"],
                    author=doc.get("author"),
                    chunk_index=i,
                    n_chunks=len(pairs),
                    char_start=pos,
                    char_end=pos + len(t),
                )
            )
            pos += len(t)
        yield chunks, level, seam_hard


def run_chunking(
    corpus_path: Path, enc: tiktoken.Encoding, budget: int, out_path: Path
) -> ChunkRunStats:
    """Chunk the corpus to out_path (JSONL, one ChunkDoc per line) and
    aggregate run stats. All invariants enforced by chunk_corpus."""
    stats = ChunkRunStats()
    # create the doc stream (and fire its missing-corpus check) BEFORE the
    # output file exists - no empty artifact on error (design-review 2026-07)
    doc_stream = chunk_corpus(corpus_path, enc, budget)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        for chunks, level, seam_hard in doc_stream:
            src = chunks[0].source
            stats.ladder_by_source.setdefault(src, {})
            stats.ladder_by_source[src][level.label] = (
                stats.ladder_by_source[src].get(level.label, 0) + 1
            )
            stats.n_docs += 1
            stats.n_docs_split += level is not ChunkLevel.PASS_THROUGH
            stats.seam_hard_splits += seam_hard
            for c in chunks:
                f.write(c.model_dump_json() + "\n")
                stats.n_chunks += 1
                stats.n_tokens_total += c.n_tokens
                stats.chunk_token_lengths.append(c.n_tokens)
            if stats.n_docs % 20000 == 0:
                log.info("chunked %d docs -> %d chunks", stats.n_docs, stats.n_chunks)
    return stats


def write_chunks_report(
    out: Path,
    stats: ChunkRunStats,
    budget: int,
    crop_fraction: float,
    tokenizer_name: str,
    corpus_sha256: str,
) -> Path:
    lengths = sorted(stats.chunk_token_lengths)
    L: list[str] = []
    L.append(generated_marker("cankar tokenizer chunk", snapshot=True))
    L.append("")
    L.append("# Chunks (Phase 2 - ADR 0012)")
    L.append("")
    L.append(f"Tokenizer `{tokenizer_name}`, budget {budget} tokens (== Phase 3")
    L.append("max_seq_len; re-chunk if that changes). Corpus sha256")
    L.append(f"`{corpus_sha256}`.")
    L.append("")
    L.append(f"- docs: {stats.n_docs:,} -> chunks: {stats.n_chunks:,}")
    L.append(f"  ({stats.n_docs_split:,} docs split)")
    L.append(f"- total tokens: {stats.n_tokens_total:,} (sum of per-chunk encodes;")
    L.append("  differs from token-stats.md's whole-doc encode total by seam")
    L.append("  re-tokenization - regex BPE is not count-preserving across splits)")
    L.append(
        f"- chunk tokens p50 {percentile(lengths, 0.5):,}, "
        f"p95 {percentile(lengths, 0.95):,}, max {lengths[-1]:,}"
    )
    L.append(
        f"- chunks at exactly budget: {sum(1 for x in lengths if x == budget):,}; "
        f"under 64 tokens: {sum(1 for x in lengths if x < 64):,} "
        "(small chunks are bestfit row-fillers, not waste - critique A-3)"
    )
    L.append(
        f"- seam-overflow hard splits in pack-verify: {stats.seam_hard_splits:,} "
        "(invisible to the ladder table below - counted separately)"
    )
    L.append("")
    L.append("## Simulated BOS-bestfit crop loss (critique A-6)")
    L.append("")
    L.append(f"Replaying nanochat's packing over the emitted chunk lengths at T={budget}:")
    L.append(f"**{100 * crop_fraction:.2f}%** of tokens cropped (vs ~35% FineWeb reference,")
    L.append("vs catastrophic-on-literary unchunked - the chunk-to-fit rationale).")
    L.append("")
    L.append("## Fallback-ladder usage (deepest level per doc)")
    L.append("")
    labels = [lv.label for lv in ChunkLevel]
    L.append("| source | " + " | ".join(labels) + " |")
    L.append("|---|" + "---|" * len(labels))
    for src in sorted(stats.ladder_by_source):
        row = stats.ladder_by_source[src]
        cells = " | ".join(f"{row.get(label, 0):,}" for label in labels)
        L.append(f"| {src} | {cells} |")
    write_report(out, L)
    return out


def simulate_bestfit_crop(lengths: list[int], budget: int, buffer_size: int = 1000) -> float:
    """Replay nanochat's BOS-bestfit packing over emitted chunk token lengths
    (+1 BOS each) and return the cropped-token fraction (critique A-6).
    Faithful to dataloader.py: largest-fit first, crop shortest on stall."""
    capacity = budget + 1
    stream = iter(lengths)
    buffer: list[int] = []
    total = 0
    cropped = 0
    exhausted = False
    while not exhausted or buffer:
        pos = 0
        while pos < capacity:
            while len(buffer) < buffer_size and not exhausted:
                try:
                    n = next(stream) + 1  # +1: loader prepends BOS per chunk
                    buffer.append(n)
                    total += n
                except StopIteration:
                    exhausted = True
            if not buffer:
                break
            remaining = capacity - pos
            fits = [n for n in buffer if n <= remaining]
            if fits:
                best = max(fits)
                buffer.remove(best)
                pos += best
            else:
                shortest = min(buffer)
                buffer.remove(shortest)
                cropped += shortest - remaining
                pos = capacity
        if exhausted and not buffer:
            break
    return cropped / total if total else 0.0
