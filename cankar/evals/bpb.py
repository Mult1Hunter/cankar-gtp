"""Deterministic held-out BPB harness (ADR 0013).

The harness produces no real number until Phase 3 supplies a trained model;
what ships now is the piece that must be right and is testable now: the eval
BATCHER. nanochat's training dataloader (BOS-bestfit) crops ~11-35% of tokens
and packs across document boundaries - non-deterministic and lossy, wrong for
a held-out measurement (architect critique MF-6). This batcher instead scores
every held-out token exactly once: each doc is BOS-prepended and tiled into
non-overlapping T-windows, tail padded with ignore_index (-1) targets.

The model is a duck type (BpbModel) - real checkpoint loading belongs in
cankar/model/ at Phase 3, not here. Tested against a stub model now.
"""

from __future__ import annotations

import logging
from pathlib import Path

import tiktoken
import torch

from cankar.core.errors import CankarError
from cankar.evals.vendored_bpb import BpbModel, evaluate_bpb

log = logging.getLogger("cankar.evals")

IGNORE_INDEX = -1  # nanochat masks y < 0 out of the metric (loss_eval.py)

EvalBatch = tuple[torch.Tensor, torch.Tensor]  # (x, y), each (1, T)


def build_eval_batches(
    texts: list[str], enc: tiktoken.Encoding, seq_len: int, bos_id: int
) -> list[EvalBatch]:
    """One BOS-prepended stream per doc, tiled into non-overlapping (1, T)
    windows so every target token is scored exactly once (MF-6). The final
    window of each doc is padded: x with token 0, y with IGNORE_INDEX.

    bos_id is passed in (not imported from the tokenizer stage) so evals stays
    an independent sibling: the Phase 3 caller that owns the tokenizer resolves
    it via enc.encode_single_token('<|bos|>')."""
    if seq_len < 1:
        raise ValueError(f"seq_len must be >= 1, got {seq_len}")
    bos = bos_id
    batches: list[EvalBatch] = []
    for text in texts:
        toks = [bos, *enc.encode_ordinary(text)]
        for i in range(0, len(toks) - 1, seq_len):
            xw = toks[i : i + seq_len]
            yw = toks[i + 1 : i + 1 + seq_len]
            pad = seq_len - len(xw)
            xw = xw + [0] * pad
            yw = yw + [IGNORE_INDEX] * (seq_len - len(yw))
            batches.append(
                (
                    torch.tensor(xw, dtype=torch.long).unsqueeze(0),
                    torch.tensor(yw, dtype=torch.long).unsqueeze(0),
                )
            )
    return batches


def load_token_bytes(path: Path) -> torch.Tensor:
    """The int32 byte-length-per-token tensor the selected tokenizer emitted
    (cankar tokenizer train). BPB indexes target tokens into it."""
    if not path.exists():
        raise CankarError(f"token_bytes.pt missing: {path} (run: cankar tokenizer train)")
    return torch.load(path, map_location="cpu")


def holdout_bpb(
    model: BpbModel,
    texts: list[str],
    enc: tiktoken.Encoding,
    token_bytes: torch.Tensor,
    seq_len: int,
    bos_id: int,
) -> float:
    """Held-out BPB for a checkpoint over the frozen held-out texts."""
    batches = build_eval_batches(texts, enc, seq_len, bos_id)
    if not batches:
        return float("inf")
    return evaluate_bpb(model, batches, len(batches), token_bytes)
