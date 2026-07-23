"""Token stats per source x author + Phase 3 sizing inputs (ROADMAP Phase 2).

One corpus pass with the selected tokenizer. Beyond the per-author table
(the deliverable), records what Phase 3 will otherwise re-measure: total
tokens, the Cankar-slice count (sizes Phase 4 continued pretraining and
TinyCankar), and steps-per-epoch reference math (critique A-5).
"""

from __future__ import annotations

import logging
from pathlib import Path

import tiktoken
from pydantic import BaseModel

from cankar.core.jsonl import iter_jsonl_docs
from cankar.core.reports import generated_marker, write_report
from cankar.tokenizer.chunk import DEFAULT_BUDGET

log = logging.getLogger("cankar.tokenizer")

CANKAR_AUTHOR = "Ivan Cankar"
# one T, one name (design-review 2026-07): steps/epoch math must follow a
# budget change, or the report prints numbers for the wrong context length
REFERENCE_T = DEFAULT_BUDGET
REFERENCE_BATCH_SIZES = (16, 32)


class GroupStats(BaseModel):
    n_docs: int = 0
    n_words: int = 0
    n_tokens: int = 0


def collect(corpus_path: Path, enc: tiktoken.Encoding) -> dict[tuple[str, str], GroupStats]:
    """Stats keyed on (source, author) - author '-' for unattributed docs."""
    groups: dict[tuple[str, str], GroupStats] = {}
    n = 0
    for doc in iter_jsonl_docs(corpus_path, missing_hint="run: cankar corpus merge"):
        key = (doc["source"], doc.get("author") or "-")
        g = groups.setdefault(key, GroupStats())
        g.n_docs += 1
        g.n_words += len(doc["text"].split())
        g.n_tokens += len(enc.encode_ordinary(doc["text"]))
        n += 1
        if n % 20000 == 0:
            log.info("stats: %d docs", n)
    return groups


def write_stats_report(
    out: Path, groups: dict[tuple[str, str], GroupStats], tokenizer_name: str, corpus_sha256: str
) -> Path:
    total_docs = sum(g.n_docs for g in groups.values())
    total_words = sum(g.n_words for g in groups.values())
    total_tokens = sum(g.n_tokens for g in groups.values())
    cankar_tokens = sum(g.n_tokens for (_, a), g in groups.items() if a == CANKAR_AUTHOR)

    L: list[str] = []
    L.append(generated_marker("cankar tokenizer stats", snapshot=True))
    L.append("")
    L.append("# Token stats (Phase 2)")
    L.append("")
    L.append(f"Tokenizer: `{tokenizer_name}`. Corpus sha256 `{corpus_sha256}`.")
    L.append("Word = `str.split()` token. Tokens = `encode_ordinary`, BOS excluded.")
    L.append("")
    L.append("## Per source x author")
    L.append("")
    L.append("| source | author | docs | words | tokens | token share |")
    L.append("|---|---|---|---|---|---|")
    for (source, author), g in sorted(groups.items()):
        L.append(
            f"| {source} | {author} | {g.n_docs:,} | {g.n_words:,} "
            f"| {g.n_tokens:,} | {100 * g.n_tokens / total_tokens:.2f}% |"
        )
    L.append(f"| **total** | | {total_docs:,} | {total_words:,} | {total_tokens:,} | 100.00% |")
    L.append("")
    L.append("## Phase 3 sizing inputs")
    L.append("")
    L.append(f"- Total tokens: **{total_tokens:,}** (one epoch)")
    L.append(f"- Cankar slice: **{cankar_tokens:,}** tokens (Phase 4 continued")
    L.append("  pretraining + Phase 2.5 TinyCankar sizing)")
    L.append(f"- Steps/epoch at T={REFERENCE_T} (single device):")
    for b in REFERENCE_BATCH_SIZES:
        steps = total_tokens // (b * REFERENCE_T)
        L.append(f"  - B={b}: {b * REFERENCE_T:,} tokens/step -> {steps:,} steps/epoch")
    L.append("")
    L.append("## Warning for Phase 3 data adaptation")
    L.append("")
    L.append("chunks.jsonl is corpus-ordered (wikipedia-dominated tail). nanochat's")
    L.append("split convention is last-parquet-is-val: an order-preserving parquet")
    L.append("conversion makes val a wikipedia-tail-only set. Shuffle at conversion")
    L.append("time (Phase 3), after the Phase 2.25 holdout exclusion.")
    write_report(out, L)
    return out
