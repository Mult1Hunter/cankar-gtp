"""Evals-stage CLI subcommands - the ONLY argparse holder for this stage.

Registered under the single `cankar` console entry (ADR 0007):
    cankar evals holdout-freeze --name v8192

The held-out BPB harness (cankar.evals.bpb) has no CLI command yet: it needs
a trained model, which Phase 3 supplies. It ships as tested library
scaffolding (deterministic batcher + vendored metric), wired in at Phase 3.
"""

from __future__ import annotations

import argparse
import logging

from cankar.core.encoding import load_encoding
from cankar.core.manifest import git_sha, sha256_of, utc_now_iso, write_manifest
from cankar.core.paths import holdout_manifest, holdout_report, merged_shard
from cankar.evals import holdout

log = logging.getLogger("cankar.evals")


def _holdout_freeze(args: argparse.Namespace) -> int:
    corpus = merged_shard()
    enc = load_encoding(args.name)
    docs = holdout.cankar_docs(corpus)
    log.info("selecting holdout from %d Cankar docs", len(docs))
    params = holdout.HoldoutParams()
    result = holdout.select_holdout(docs, enc, params)
    holdout_tokens = sum(w.n_tokens for w in result.works)
    manifest = holdout.HoldoutManifest(
        corpus_sha256=sha256_of(corpus),
        tokenizer_name=args.name,
        params=params,
        cankar_total_tokens=result.cankar_total_tokens,
        holdout_tokens=holdout_tokens,
        holdout_fraction=round(holdout_tokens / result.cankar_total_tokens, 4),
        git_sha=git_sha(),
        created_at=utc_now_iso(),
        works=result.works,
        also_exclude_urls=result.also_exclude_urls,
    )
    out = write_manifest(manifest, holdout_manifest())
    report = holdout.write_holdout_report(holdout_report(), manifest, result.rejected)
    log.info(
        "froze %d works / %d tokens (%.2f%%), +%d reverse-contained urls -> %s + %s",
        len(result.works),
        holdout_tokens,
        100 * manifest.holdout_fraction,
        len(result.also_exclude_urls),
        out,
        report,
    )
    return 0


def register(parser: argparse.ArgumentParser) -> None:
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser(
        "holdout-freeze", help="freeze the held-out Cankar set before Phase 3 (ADR 0013)"
    )
    p.add_argument("--name", required=True, help="tokenizer candidate (the selected one)")
    p.set_defaults(func=_holdout_freeze)
