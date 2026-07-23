"""Vendored-constant drift check (ADR 0011).

nanochat is not importable as a dependency (torch pin conflict), so the
split pattern and special-token list are vendored verbatim. This test loads
the sibling checkout's module directly and compares - it runs only where
the checkout exists (dev machines), and skips in CI.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

from cankar.tokenizer import vendored

_CHECKOUT = Path(
    os.environ.get("NANOCHAT_CHECKOUT", str(Path.home() / "PROJECTS" / "PERSONAL" / "nanochat"))
)
NANOCHAT_TOKENIZER = _CHECKOUT / "nanochat" / "tokenizer.py"


@pytest.mark.skipif(not NANOCHAT_TOKENIZER.exists(), reason="sibling nanochat checkout not present")
def test_vendored_constants_match_sibling_checkout() -> None:
    spec = importlib.util.spec_from_file_location("nanochat_tokenizer", NANOCHAT_TOKENIZER)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.SPECIAL_TOKENS == vendored.SPECIAL_TOKENS
    assert mod.SPLIT_PATTERN == vendored.SPLIT_PATTERN
