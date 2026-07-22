# CankarGTP - Roadmap

> A from-scratch Slovene micro-LLM (~40M params) trained on public-domain literature,
> specialized in Ivan Cankar's voice, extended with plain->Cankar style transfer via
> synthetic parallel data, orchestrated with a large knowledge model, and served for ~€0.
>
> **Hardware:** local RTX 4070 Ti Super 16GB (dev, tokenization, TinyCankar) + rented cloud GPU (long runs, ~$10-40 total)
> **Stack:** Python/uv + PyTorch + nanochat (scaled down), Claude Batch API, FastAPI, Laravel orchestrator, Astro demo page
> **Repo policy:** single public monorepo from commit #1 (github.com/Mult1Hunter/cankar-gtp - ADR 0002). Public-repo
> hygiene (.gitignore, .env.example, gitleaks pre-commit + CI, weights/data on HF Hub or R2 - never in git, milestone tags).

---

## MVP gate

**MVP = Phases 0-4 + eval numbers + static samples page + blog posts 1-2.**
Everything after Phase 4 gets an explicit go/no-go decision based on MVP quality.
Do not build serving or the Laravel orchestrator before the styler exists.

---

## Phase 0 - Environment (half a day)

- [x] uv project init
- [ ] PyTorch + CUDA 12.x; verify `torch.cuda.is_available()` (deps arrive with Phase 2/3 per pyproject policy)
- [ ] Clone nanochat; read the speedrun script end-to-end
- [ ] Watch Karpathy "Let's build GPT" (nanoGPT stays *reading material*, nanochat is the codebase)
- [ ] RunPod account + **spending limit set** + one 15-min throwaway pod to validate workflow
- [x] Repo init (public from commit #1), .gitignore, .env.example, gitleaks pre-commit hook + CI

## Phase 1 - Corpus (1-2 sessions)

- [x] Wikivir/Wikisource crawler via MediaWiki API: Cankar + 14 PD authors, attribution/catalog guards (PR #9, #10)
- [x] Works registry as source of truth + dLib.si gap-fill with OCR quality gates *(added in-flight - ADR 0004)*
- [x] Slovenian Wikipedia dump ingestion: 125,670 articles / 65.3M words, streaming
      (ShardWriter already extracted the one shared seam - the write side; the three
      acquisition sides, API/EDM/dump-stream, are genuinely divergent, so no further
      SourceCrawler protocol - that would be one-shape-fits-none)
- [x] Clean (mwparserfromhell), NFC-normalize -> JSONL shards with manifests
- [ ] Dedupe + chunk (merge stage; consumes registry/works/NOTES.md annotations; Wikipedia geo-stub near-dups)
- [ ] Stats report: tokens per source/author
- ⚠️ **Yield correction (measured 2026-07):** Cankar 1.65M words; 14 PD authors 6.0M;
      Wikipedia 65.3M -> corpus ~73M words ≈ **~110-140M tokens**. The original
      ~200-300M general-Slovene target is **unreachable from Wikipedia alone** (~half
      the low end). Options at Phase 3 sizing: accept ~120M tokens (data-constrained;
      a ~15-30M model is the honest compute-optimal-with-repetition size, not 40M -
      see Phase 3 model-size line), or add a general-Slovene source (KAS/Gigafida/CC).
      The Cankar slice (1.65M words) is the true bottleneck - Phase 5 synthetic pairs
      exist to multiply it.
- **Licensing (B5):** publish reproducible corpus-*building scripts*, not the merged corpus
  (Wikipedia is CC BY-SA; Cankar is PD; the merged blob inherits share-alike obligations)
- **Attribution:** README "Data sources" is the canonical credit statement (dLib.si
  citation required by its terms; Wikipedia CC BY-SA; Wikivir contributors) - every
  published artifact (HF datasets/models, demo pages) repeats it

## Phase 2 - Tokenizer (1 session)

- [ ] Slovene BPE via nanochat's tokenizer stage, vocab ~8-16k, trained on own corpus
- [ ] Inspect segmentation of Slovene morphology + Cankar's archaic orthography -> README material

## Phase 2.25 - Evaluation harness (1 session) *(added per Agent A4)*

- [ ] Held-out perplexity set: unseen Cankar chapters
- [ ] Style classifier (Cankar vs plain Slovene): TF-IDF + logistic regression baseline, SloBERTa if needed
- [ ] LLM-judge template for meaning preservation (used from Phase 6 on)
- [ ] Dev set design: 200 held-out pairs **+ 50 fresh drafts** (measures the distribution gap explicitly, per A1)
- Rule: every quality claim in README/blog gets a number from this harness

## Phase 2.5 - TinyCankar micro-win (few hours) *(added per Agent C2)*

- [ ] ~10M model, Cankar-only, local or ~$1 cloud rehearsal of the full pod workflow
- [ ] Save the charmingly broken samples (they are the "before" in the final before/after - unrecoverable later)
- [ ] **Publish TinyCankar samples** (LinkedIn / blog teaser) - public commitment = project survival
      (repo is public from commit #1; this milestone *promotes* it)
- [ ] Tag `v0.1-tinycankar`

## Phase 3 - Base pretrain (cloud, ~$10-15)

- [ ] Adapt corpus into nanochat's data pipeline (real work - own deliverable, per B1; budget a full session)
- [ ] **Calibration first (B3):** 30-min tokens/sec measurement + tested checkpoint-resume *before* the long run
- [ ] `setup.sh`: pod -> clone -> deps -> pull data (HF/R2) -> tmux train -> checkpoint-sync loop. Target: <5 min to training, unattended
- [ ] Cost discipline: terminate (not stop), delete volumes after sync, `--max-hours` self-terminating flag
- [ ] **Model size (revised from measured data, 2026-07):** ~120M-token budget makes
      the original 40-50M target data-constrained (Chinchilla single-epoch optimal
      for 120M tok ≈ 6M params; ~4 epochs ≈ 24M). Target **~15-30M params** and let
      the eval harness decide whether scaling up lowers held-out perplexity or just
      burns GPU. Specialization + Phase-5 synthetic pairs add effective Cankar signal.
- [ ] bf16, flash attention; W&B free tier for live loss curves (blog artifact)
- [ ] Model config: RunPod 4090 for experiments, A100 for the final run
- Reference: total compute ~ 50-100x *less* than nanochat's $100 speedrun; budget anxiety = zero

## Phase 4 - Cankar specialization (hours)

- [ ] Continued pretraining on Cankar-only corpus -> CankarGTP v1 (continuation model)
- [ ] Checkpoint-progression samples ("gibberish becomes Cankar") - core blog/demo content
- [ ] Run eval harness; record numbers
- [ ] **-> MVP SHIP: static samples page + blog posts 1-2. Go/no-go for everything below.**

## Phase 5 - Synthetic style pairs (1-2 sessions, ~$5-15 API)

- [ ] Chunk Cankar into 5-15k passages (2-6 sentences)
- [ ] Claude Batch API de-styling -> plain modern Slovene; pair `(plain -> original Cankar)`
- [ ] **Distribution-shift fix (A1):** ONE shared "plain Slovene register" prompt, reused verbatim for
  (a) de-styling in training data generation and (b) draft-writing at inference. Non-negotiable design invariant.
- [ ] QA: spot-check 50-100 pairs; auto-filter bottom 5-10% (length-ratio + LLM meaning score)
- [ ] Publish dataset to HF Hub (`cankar-parallel`) - target side PD, source side own output; standalone contribution

## Phase 6 - Style-transfer SFT (hours)

- [ ] Adapt nanochat's SFT stage to `<plain> ... <cankar> ...` format
- [ ] Evaluate on held-out pairs AND fresh drafts (the gap between the two is the honest headline number)
- [ ] Product framing (A3): this is a **prose-poem / črtica styler**, not a poem generator - brand it honestly

## Phase 7 - Serving v1 (1 session)

- [ ] FastAPI sidecar, `/generate`, loads PyTorch checkpoint on **CPU** - deploy on existing VPS (marginal cost €0)
  (~80MB fp16 model, ~200-500MB RAM, 50-200+ tok/s on CPU - no GPU hosting needed)
- [ ] HF Space (free CPU, Gradio) as public mirror + fallback link
- [ ] GGUF/Ollama export: **stretch goal only** (B2 - custom arch/tokenizer may not convert; never promise it)

## Phase 7.5 - MILESTONE: In-browser model (v1.5 flex)

- [ ] ONNX export of the trained model (real work - same risk category as GGUF; timebox it)
- [ ] transformers.js / ONNX Runtime Web integration on the demo site
      (site framework: Phase 8 open decision)
- [ ] ~40MB quantized download, cached; generation fully client-side
- **Payoff:** €0 serving, infinite scale, HN-front-page-proof, and the demo line
  "this Slovene LLM is running in your browser right now"
- Fallback if export fights back: browser demo calls the VPS FastAPI endpoint; ONNX ships later

## Phase 8 - Orchestration + two-tier demo (2-3 sessions, Laravel home turf)

> **Open decision (parked 2026-07, due at this phase's go/no-go): web stack.**
> Challenged: Laravel + Astro + FastAPI = three deployables for a solo project, and
> FastAPI (Phase 7, mandatory) could absorb the orchestration. Options: keep both
> (portfolio claim + static demo), Laravel-only web, cut Laravel (Astro + FastAPI).
> Decide via ADR at gate time; Laravel/Astro lines below and the `apps/web` /
> `apps/orchestrator` rows in ADR 0002 are **provisional** until then.

- [ ] Tier 1 "Piši kot Cankar" - free/unlimited, local model only (browser or VPS), zero marginal cost
- [ ] Tier 2 "Vprašaj Cankarja" - knowledge model (behind an interface - provider-agnostic, per C5) ->
  plain draft in the shared register -> styler -> cleanup pass (restores mangled named entities, per A2)
- [ ] Abuse controls: Cloudflare Turnstile, per-IP rate limits, **daily global spend cap** -> degrades to Tier 1
- [ ] Cost reality: ~$0.001-0.005/generation; 1k uses ~ few $; viral day ~ $20-50 capped
- [ ] Demo UX (C1): 10-second graspability - text box -> output -> one-line "trained from scratch on rented GPUs
  for $15" caption; architecture one click below. Centerpiece of the Astro site relaunch
  at nextgen-solutions.xyz (+ unblocks the LinkedIn post)

## Phase 9 - GaMS v2 (later; separate go/no-go)

- [ ] Same pair dataset. Prototype: LoRA on GaMS-2B (fast loop). Quality: QLoRA on GaMS-9B (fits 16GB w/ Unsloth)
- [ ] Enters HF Transformers + PEFT ecosystem (deliberately second, after from-scratch understanding)
- [ ] **Release as downloadable weights on HF ("run it in Ollama"), not hosted** - live demo stays on the free 40M
  model; v2 is proof of range, not infrastructure ($10-50/mo GPU serverless not worth it for a demo)
- [ ] README answers "why not just GaMS from the start?" up front (C3): from-scratch = full-stack understanding;
  GaMS fine-tune = practical delivery. One project, both claims.

## Phase 10 - Content (runs *during*, not after - C5)

- [ ] Blog 1: building a Slovene corpus from Wikisource
- [ ] Blog 2: training an LLM from scratch on rented GPUs for $15 (loss curves, evolving samples, nvtop screenshots
  - capture artifacts as they happen; unrecoverable afterward)
- [ ] Blog 3: two-model orchestration (knowledge model + own styler + Laravel)
- [ ] README: architecture diagram, eval numbers, "why from scratch" section, reproducibility ($10 RunPod path
  AND 16GB-consumer-card path documented - environment-agnostic training script)
- [ ] Disclaimer (C4): AI pastiche, educational, unaffiliated with Cankar institutions - one sentence, mandatory
- [ ] HF uploads: model weights, pairs dataset, (v2 weights later)

---

## Risk register (from agent review)

*Codes (A1 ... C5) index the pre-kickoff multi-agent plan review; kept for traceability.*

| # | Risk | Mitigation | Phase |
|---|------|-----------|-------|
| A1 | Train/inference distribution mismatch in style pairs | Shared register prompt; fresh-draft dev set | 5, 6 |
| A2 | Modern vocab/named entities mangled by tiny model | Wikipedia in pretrain mix; cleanup pass restores entities | 1, 8 |
| A3 | "Poem" overpromise (Cankar = prose) | Brand as prose-poem/črtica styler | 6, 8 |
| A4 | No measurable quality claims | Eval harness before long training | 2.25 |
| B1 | nanochat pipeline assumes FineWeb layout | Data-adaptation is its own budgeted deliverable | 3 |
| B2 | GGUF/ONNX export of custom arch may fail | Stretch goals, timeboxed; FastAPI is the primary path | 7, 7.5 |
| B3 | Interrupted runs / unmeasured estimates | Calibration run; tested resume; cloud offloads workstation | 3 |
| B4 | Scope death (solo, evenings) | Hard MVP gate; Laravel last; per-phase go/no-go | gate |
| B5 | Corpus redistribution licensing | Ship scripts, not merged corpus | 1 |
| C2 | Mid-project motivation collapse | TinyCankar micro-win + samples post at 2.5 | 2.5 |
| - | Secrets in public history | Public from commit #1: gitleaks hook + CI, `public-hygiene` skill pre-push | 0 |
| - | API cost abuse on public demo | Turnstile, rate limits, hard daily cap -> Tier 1 degrade | 8 |

## Budget summary

| Item | Cost |
|---|---|
| Cloud pretraining (incl. failed runs) | $15-40 one-time |
| Claude Batch API (pair generation) | $5-15 one-time |
| Serving (VPS already owned + HF free tier + browser) | ~€0/mo |
| Tier-2 demo API usage | capped, ~€0-5/mo |
| **Total to full v1** | **~ one dinner in Ljubljana** |

## Timeline

6-10 weeks part-time. MVP shippable ~week 3-4. Next concrete action: **Phase 1 Wikivir crawler** (cloud-independent, everything downstream feeds on it).

---

## Appendix - repo policy pointers

Layout, visibility, naming: **ADR 0002**, engineering/validation system: **ADR 0003** ,
human workflow (setup, commit types, PR rules): **CONTRIBUTING.md**, pre-push
procedure: `public-hygiene` skill, staged-content rules: `commit` skill.

Private material (notes, plans, deploy inventory, progress files) lives in the sibling
private repo `../cankar-gtp-meta` - never here. Optional symlink
`notes -> ../cankar-gtp-meta/notes` (gitignored); personal ignores that shouldn't
pollute the shared `.gitignore` go in `.git/info/exclude`.
