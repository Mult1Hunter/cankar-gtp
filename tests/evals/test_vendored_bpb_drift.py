"""Numerical drift check: our vendored evaluate_bpb vs the sibling's (ADR 0013).

nanochat is not importable as a package (torch pin), but loss_eval.py depends
only on torch, so it can be exec'd from the sibling checkout for a
same-inputs/same-output comparison. Runs only where the checkout exists.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest
import torch

from cankar.evals.vendored_bpb import evaluate_bpb

_CHECKOUT = Path(
    os.environ.get("NANOCHAT_CHECKOUT", str(Path.home() / "PROJECTS" / "PERSONAL" / "nanochat"))
)
LOSS_EVAL = _CHECKOUT / "nanochat" / "loss_eval.py"


class StubModel:
    def __call__(self, x: torch.Tensor, y: torch.Tensor, loss_reduction: str) -> torch.Tensor:
        # deterministic, position-dependent loss so masking differences would show
        return (x.float() % 7 + 1) * 0.3

    def get_device(self) -> str:
        return "cpu"


def _batches():
    torch.manual_seed(0)
    out = []
    for _ in range(3):
        x = torch.randint(0, 40, (1, 12))
        y = x.roll(-1, dims=1).clone()
        y[0, -3:] = -1  # some ignored targets
        out.append((x, y))
    return out


@pytest.mark.skipif(not LOSS_EVAL.exists(), reason="sibling nanochat checkout not present")
def test_vendored_bpb_matches_sibling() -> None:
    spec = importlib.util.spec_from_file_location("nanochat_loss_eval", LOSS_EVAL)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    token_bytes = torch.randint(1, 5, (40,), dtype=torch.int32)
    token_bytes[0] = 0  # a special token contributes no bytes

    ours = evaluate_bpb(StubModel(), _batches(), 3, token_bytes)
    theirs = mod.evaluate_bpb(StubModel(), _batches(), 3, token_bytes)
    assert ours == pytest.approx(theirs, rel=1e-9)
