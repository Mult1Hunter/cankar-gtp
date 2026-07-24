"""bits-per-byte metric vendored verbatim from nanochat (ADR 0013).

nanochat is not importable (torch pin conflict - see cankar/tokenizer/
vendored.py), so its held-out metric is vendored here and kept NUMERICALLY
EQUIVALENT to the sibling (only added type hints, the Protocol, and a
variable rename differ from the source). Two guards: a golden test pinned in
CI (tests/evals/test_bpb.py) and a same-inputs/same-output drift test against
the sibling checkout (tests/evals/test_vendored_bpb_drift.py, dev-only).
Provenance: nanochat commit 92d63d4e8bb4df75c3b71618f31ddde2378b2bcd,
nanochat/loss_eval.py.

BPB (not raw perplexity) is the held-out metric because it is vocab-size
independent: sum the loss in nats, sum the target-token byte lengths, divide.
A vocab change stays apples-to-apples. Re-vendor and bump the commit hash on
any upstream change; keep the math faithful.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Protocol

import torch
import torch.distributed as dist

NANOCHAT_COMMIT = "92d63d4e8bb4df75c3b71618f31ddde2378b2bcd"


class BpbModel(Protocol):
    """The two-method duck type evaluate_bpb needs (nanochat gpt.py:316,520)."""

    def __call__(self, x: torch.Tensor, y: torch.Tensor, loss_reduction: str) -> torch.Tensor: ...

    def get_device(self) -> torch.device | str: ...


@torch.no_grad()
def evaluate_bpb(
    model: BpbModel,
    batches: Iterable[tuple[torch.Tensor, torch.Tensor]],
    steps: int,
    token_bytes: torch.Tensor,
) -> float:
    """Bits per byte over `steps` (x, y) batches. Special tokens and ignored
    targets (y < 0) carry 0 bytes and drop out; the loss is normalized by the
    byte length of the real target tokens. Vendored verbatim - keep faithful."""
    total_nats = torch.tensor(0.0, dtype=torch.float32, device=model.get_device())
    total_bytes = torch.tensor(0, dtype=torch.int64, device=model.get_device())
    batch_iter = iter(batches)
    for _ in range(steps):
        x, y = next(batch_iter)
        loss2d = model(x, y, loss_reduction="none")  # (B, T)
        loss2d = loss2d.view(-1)
        y = y.view(-1)
        if (y.int() < 0).any():
            valid = y >= 0
            y_safe = torch.where(valid, y, torch.zeros_like(y))
            num_bytes2d = torch.where(
                valid, token_bytes[y_safe], torch.zeros_like(y, dtype=token_bytes.dtype)
            )
            total_nats += (loss2d * (num_bytes2d > 0)).sum()
            total_bytes += num_bytes2d.sum()
        else:
            num_bytes2d = token_bytes[y]
            total_nats += (loss2d * (num_bytes2d > 0)).sum()
            total_bytes += num_bytes2d.sum()
    world_size = dist.get_world_size() if dist.is_initialized() else 1
    if world_size > 1:
        dist.all_reduce(total_nats, op=dist.ReduceOp.SUM)
        dist.all_reduce(total_bytes, op=dist.ReduceOp.SUM)
    # nanochat rebinds total_nats/total_bytes here; split names to stay typed
    nats = total_nats.item()
    n_bytes = total_bytes.item()
    if n_bytes == 0:
        return float("inf")
    return nats / (math.log(2) * n_bytes)
