# ADR 0001 — nanochat (scaled down) as the training codebase

**Status:** accepted · 2026-07

## Context

Options for the from-scratch training loop: fork nanoGPT (simple, ~600 lines, but
deprecated by its author in Nov 2025), use HF Transformers `Trainer` (production-grade,
but hides the loop we're trying to learn), or adapt nanochat (current, full pipeline:
tokenizer → pretrain → SFT → eval → chat UI, but designed around an 8xH100 speedrun).

## Decision

Use **nanochat scaled down** (single GPU, ~30–50M params, own Slovene corpus) as the
codebase. Use nanoGPT and Karpathy's "Let's build GPT" only as prerequisite reading.
HF Transformers + PEFT enter later, deliberately, for the GaMS fine-tune (v2).

## Rationale

- nanochat has tokenizer training and an SFT stage as first-class pipeline steps —
  both are hard requirements here (custom Slovene BPE; `<plain>→<cankar>` pairs).
- Modern architecture defaults; conventions transfer to current models.
- Known cost: its data pipeline assumes FineWeb-style shards — adapting our corpus is
  budgeted as its own deliverable (ROADMAP Phase 3, risk B1).

## Consequences

Eval/serving code partially inherited for free; we accept fighting some big-iron
defaults (batch sizes, sharding) in exchange for not hand-building tokenizer + SFT
stages on a deprecated codebase.
