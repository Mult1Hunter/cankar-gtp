"""Constants vendored verbatim from nanochat (ADR 0011).

nanochat cannot be a dependency: it pins torch==2.9.1 against our >=2.13,
and a sys.path import of a sibling checkout is unpinned, untracked
provenance (ADR 0003). The Phase 3 coupling surface is deliberately tiny -
the split pattern, the special-token list, and the two-file artifact recipe
(tokenizer.pkl + token_bytes.pt) - so it is vendored verbatim here and
drift-checked against the sibling checkout when present
(tests/tokenizer/test_vendored_drift.py).

Provenance: nanochat commit 92d63d4e8bb4df75c3b71618f31ddde2378b2bcd,
nanochat/tokenizer.py. Do not edit these values; re-vendor and bump the
commit hash instead.
"""

from __future__ import annotations

NANOCHAT_COMMIT = "92d63d4e8bb4df75c3b71618f31ddde2378b2bcd"

# nanochat/tokenizer.py SPECIAL_TOKENS - verbatim. Base pretraining touches
# only <|bos|>; the chat tokens sit idle until the SFT phase, but the full
# list must be present so vocab ids line up with nanochat checkpoints.
SPECIAL_TOKENS = [
    "<|bos|>",
    "<|user_start|>",
    "<|user_end|>",
    "<|assistant_start|>",
    "<|assistant_end|>",
    "<|python_start|>",
    "<|python_end|>",
    "<|output_start|>",
    "<|output_end|>",
]

BOS_TOKEN = "<|bos|>"

# nanochat/tokenizer.py SPLIT_PATTERN - verbatim (GPT-4 style, \p{N}{1,2}).
# The English contraction branch fires on embedded English inside Wikipedia
# articles (frequent) - harmless; Slovene verse elisions (al', tak') route
# through the punctuation branch instead. Kept byte-identical for Phase 3
# checkpoint compatibility.
SPLIT_PATTERN = (
    r"""'(?i:[sdmt]|ll|ve|re)|[^\r\n\p{L}\p{N}]?+\p{L}+|\p{N}{1,2}"""
    r"""| ?[^\s\p{L}\p{N}]++[\r\n]*|\s*[\r\n]|\s+(?!\S)|\s+"""
)
