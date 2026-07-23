"""Fertility evaluation and the committed tokenizer-eval report.

Slice key (architect critique MF-3): `source` alone cannot express the
decision trigger - Cankar is an author inside wikivir, not a source. Slices:
CANKAR (author == "Ivan Cankar"), WIKIPEDIA (source == "wikipedia"),
LITERARY (everything else: other PD authors incl. comma-joined multi-author
values, dlib, gapfill). Genre classes (verse, drama, OCR noise) have no
metadata field and are covered by fixtures, not slice metrics.

Embedding-share math (critique MF-2): nanochat's GPT carries value
embeddings - one vocab-sized table per every-other layer - so vocab-coupled
params are (2 + ceil(L/2)) * V * dim, not 2 * V * dim. The report presents
totals per (depth, vocab) with model_dim = 64 * depth (base_train defaults);
whether the Phase 3 budget counts embeddings is decided at Phase 3 sizing.
"""

from __future__ import annotations

import logging
import math
import tomllib
import unicodedata
from enum import StrEnum
from pathlib import Path

import tiktoken
from pydantic import BaseModel

from cankar.core.errors import CankarError
from cankar.core.metrics import percentile
from cankar.core.reports import generated_marker, write_report
from cankar.tokenizer.train import iter_corpus_docs

log = logging.getLogger("cankar.tokenizer")

CANKAR_AUTHOR = "Ivan Cankar"
SOFT_HYPHEN = "\u00ad"  # escaped: a literal soft hyphen is invisible in source
EVAL_DEPTHS = (4, 6, 8)  # reachable depths for a 15-50M model (see report)


class Slice(StrEnum):
    CANKAR = "cankar"
    LITERARY = "literary"
    WIKIPEDIA = "wikipedia"


def classify(source: str, author: str | None) -> Slice:
    if author == CANKAR_AUTHOR:
        return Slice.CANKAR
    if source == "wikipedia":
        return Slice.WIKIPEDIA
    return Slice.LITERARY


class SliceStats(BaseModel):
    n_docs: int = 0
    n_words: int = 0  # word = str.split() token, matching corpus-quality.md
    n_utf8_bytes: int = 0
    n_tokens: int = 0
    n_digit_tokens: int = 0
    per_doc_fertility: list[float] = []  # tokens/word per doc (docs with words)

    @property
    def tokens_per_word(self) -> float:
        return self.n_tokens / self.n_words if self.n_words else 0.0

    @property
    def bytes_per_token(self) -> float:
        return self.n_utf8_bytes / self.n_tokens if self.n_tokens else 0.0

    @property
    def digit_token_share(self) -> float:
        return self.n_digit_tokens / self.n_tokens if self.n_tokens else 0.0

    @property
    def fertility_p95(self) -> float:
        return float(percentile(sorted(self.per_doc_fertility), 0.95))


class CandidateEval(BaseModel):
    name: str
    vocab_size: int
    slices: dict[Slice, SliceStats]


class CorpusNotes(BaseModel):
    """Oddities measured during the pass (critique A-3) - recorded, not fixed here."""

    n_docs: int = 0
    docs_with_soft_hyphen: int = 0
    docs_with_tabs: int = 0


def _digit_token_ids(enc: tiktoken.Encoding) -> set[int]:
    special_ids = {enc.encode_single_token(s) for s in enc.special_tokens_set}
    return {
        tid
        for tid in range(enc.n_vocab)
        if tid not in special_ids and enc.decode_single_token_bytes(tid).isdigit()
    }


def evaluate_candidates(
    corpus_path: Path, encodings: dict[str, tiktoken.Encoding]
) -> tuple[list[CandidateEval], CorpusNotes]:
    """One corpus pass; every candidate encodes every document."""
    digit_ids = {name: _digit_token_ids(enc) for name, enc in encodings.items()}
    evals = {
        name: CandidateEval(
            name=name, vocab_size=enc.n_vocab, slices={s: SliceStats() for s in Slice}
        )
        for name, enc in encodings.items()
    }
    notes = CorpusNotes()
    for doc in iter_corpus_docs(corpus_path):
        text = doc["text"]
        sl = classify(doc["source"], doc.get("author"))
        n_words = len(text.split())
        n_bytes = len(text.encode("utf-8"))
        notes.n_docs += 1
        notes.docs_with_soft_hyphen += SOFT_HYPHEN in text
        notes.docs_with_tabs += "\t" in text
        for name, enc in encodings.items():
            ids = enc.encode_ordinary(text)
            st = evals[name].slices[sl]
            st.n_docs += 1
            st.n_words += n_words
            st.n_utf8_bytes += n_bytes
            st.n_tokens += len(ids)
            st.n_digit_tokens += sum(1 for t in ids if t in digit_ids[name])
            if n_words:
                st.per_doc_fertility.append(len(ids) / n_words)
        if notes.n_docs % 20000 == 0:
            log.info("evaluated %d docs", notes.n_docs)
    return sorted(evals.values(), key=lambda e: e.vocab_size), notes


def vocab_param_rows(vocab_size: int) -> list[dict[str, float]]:
    """(depth, dim, block, vocab-coupled, total, share) under base_train defaults."""
    rows = []
    for depth in EVAL_DEPTHS:
        dim = 64 * depth
        block = 12 * dim * dim * depth
        vocab = (2 + math.ceil(depth / 2)) * vocab_size * dim
        total = block + vocab
        rows.append(
            {
                "depth": depth,
                "dim": dim,
                "block_m": block / 1e6,
                "vocab_m": vocab / 1e6,
                "total_m": total / 1e6,
                "share": vocab / total,
            }
        )
    return rows


def load_probes(probes_path: Path) -> dict[str, list[str]]:
    with probes_path.open("rb") as f:
        data = tomllib.load(f)
    probes = data.get("probes", {})
    if not probes:
        raise CankarError(f"no [probes] tables in {probes_path}")
    return {k: list(v) for k, v in probes.items()}


def segment(enc: tiktoken.Encoding, word: str) -> str:
    """Human-readable split, e.g. 'sol|nce'. NFC input is a project invariant."""
    if not unicodedata.is_normalized("NFC", word):
        raise CankarError(f"probe word not NFC-normalized: {word!r}")
    pieces = [
        enc.decode_single_token_bytes(t).decode("utf-8", errors="replace")
        for t in enc.encode_ordinary(word)
    ]
    return "|".join(pieces)


def write_eval_report(
    out: Path,
    corpus_sha256: str,
    evals: list[CandidateEval],
    notes: CorpusNotes,
    probes: dict[str, list[str]],
    encodings: dict[str, tiktoken.Encoding],
    selection: str | None,
    selection_reason: str | None,
) -> Path:
    """Deterministic snapshot report (fixed float formats, sorted ordering) -
    regenerating from the same corpus + artifacts is byte-identical."""
    L: list[str] = []
    L.append(generated_marker("cankar tokenizer eval", snapshot=True))
    L.append("")
    L.append("# Tokenizer evaluation (Phase 2)")
    L.append("")
    L.append(f"Corpus: `data/merged/corpus.jsonl` sha256 `{corpus_sha256}`")
    L.append(f"Docs: {notes.n_docs:,}. Word = `str.split()` token (matches corpus-quality.md).")
    L.append("Fertility = tokens/word; p95 is the per-doc tail (non-Latin spans and")
    L.append("OCR debris hide in means - critique A-3). Digit share = emitted tokens")
    L.append("that are ASCII-digit-only (split pattern caps runs at \\p{N}{1,2}).")
    L.append("")
    L.append("## Per-slice fertility")
    L.append("")
    L.append("| candidate | slice | docs | words | tok/word | p95 | bytes/tok | digit% |")
    L.append("|---|---|---|---|---|---|---|---|")
    for ev in evals:
        for sl in Slice:
            st = ev.slices[sl]
            L.append(
                f"| {ev.name} | {sl} | {st.n_docs:,} | {st.n_words:,} "
                f"| {st.tokens_per_word:.3f} | {st.fertility_p95:.3f} "
                f"| {st.bytes_per_token:.3f} | {100 * st.digit_token_share:.2f} |"
            )
    L.append("")
    L.append("## Cankar-vs-Wikipedia fertility ratio (weighted-mix trigger)")
    L.append("")
    for ev in evals:
        cankar = ev.slices[Slice.CANKAR].tokens_per_word
        wiki = ev.slices[Slice.WIKIPEDIA].tokens_per_word
        ratio = cankar / wiki if wiki else 0.0
        L.append(f"- {ev.name}: {cankar:.3f} / {wiki:.3f} = **{ratio:.3f}**")
    L.append("")
    L.append("## Vocab cost under nanochat's architecture (critique MF-2)")
    L.append("")
    L.append("Vocab-coupled params = (2 + ceil(L/2)) x V x dim (wte + untied lm_head +")
    L.append("per-every-other-layer value embeddings); dim = 64 x depth (base_train")
    L.append("defaults). Whether the Phase 3 budget counts embeddings is decided at")
    L.append("Phase 3 sizing - both numbers are here.")
    L.append("")
    L.append("| candidate | depth | dim | block M | vocab M | total M | vocab share |")
    L.append("|---|---|---|---|---|---|---|")
    for ev in evals:
        for r in vocab_param_rows(ev.vocab_size):
            L.append(
                f"| {ev.name} | {r['depth']} | {r['dim']} | {r['block_m']:.2f} "
                f"| {r['vocab_m']:.2f} | {r['total_m']:.2f} | {100 * r['share']:.1f}% |"
            )
    L.append("")
    L.append("## Morphology probes")
    L.append("")
    for group in sorted(probes):
        L.append(f"### {group}")
        L.append("")
        header = " | ".join(ev.name for ev in evals)
        L.append(f"| word | {header} |")
        L.append("|" + "---|" * (len(evals) + 1))
        for word in probes[group]:
            cells = " | ".join(segment(encodings[ev.name], word) for ev in evals)
            L.append(f"| {word} | {cells} |")
        L.append("")
    L.append("## Corpus notes (measured during the pass)")
    L.append("")
    L.append(f"- docs containing U+00AD soft hyphen: {notes.docs_with_soft_hyphen}")
    L.append("  (survives NFC, category Cf: fractures words invisibly - candidate")
    L.append("  for a corpus errata pass, out of scope here)")
    L.append(f"- docs containing tabs: {notes.docs_with_tabs} (table/OCR debris)")
    L.append("")
    L.append("## Selection")
    L.append("")
    if selection:
        L.append(f"Selected candidate: **{selection}**. {selection_reason or ''}".rstrip())
    else:
        L.append("Pending - selection is recorded here by `cankar tokenizer eval --select`.")
    write_report(out, L)
    return out
