# CankarGTP

[![CI](https://github.com/Mult1Hunter/cankar-gtp/actions/workflows/ci.yml/badge.svg)](https://github.com/Mult1Hunter/cankar-gtp/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

> *Mati, ali je model že konvergiral?*

A Slovene micro language model (~40M parameters) trained **from scratch** - custom BPE
tokenizer, pretraining on public-domain Slovenian literature and Wikipedia, then
specialized in the prose voice of **Ivan Cankar** (1876-1918), with a plain->Cankar
style-transfer stage trained on synthetic parallel data.

**Status:** Phase 1 (corpus building). See [ROADMAP.md](ROADMAP.md) for the full
plan, risk register, and budget (spoiler: the whole thing costs about one dinner in
Ljubljana).

## Why from scratch, when GaMS exists?

Deliberately both, in order: the from-scratch model demonstrates the full stack
(tokenizer -> pretraining -> SFT -> serving) on consumer/rented hardware; a later
GaMS fine-tune on the same dataset demonstrates practical delivery with modern
open models. One project, two claims. Details in the roadmap.

## Reproducing

Corpus-building scripts are published here (the merged corpus itself is not
redistributed - licensing note in ROADMAP Phase 1):

```bash
uv sync
uv run scripts/crawl_wikivir.py --category "Kategorija:Ivan Cankar" \
    --out data/corpus/cankar.jsonl
```

## Contributing & security

See [CONTRIBUTING.md](CONTRIBUTING.md) (setup, commit conventions) and
[SECURITY.md](SECURITY.md) (private vulnerability reporting).

## License

Code is [MIT](LICENSE). The merged training corpus is not redistributed; model
weights will be licensed at Hugging Face release time.

---

Built by [Matic Korošec](https://nextgen-solutions.xyz) - training logs and
write-ups land on the site as the project progresses.

*AI pastiche for educational purposes. Not affiliated with any Cankar institution,
memorial, or the Vrhnika tourist board. Cankar's works are in the public domain.*
