"""The single console entry point: `cankar <stage> <command>` (ADR 0007).

Each stage package owns exactly one cli.py that registers its subcommands
here. There is no scripts/ directory; a "quick script" is a stage module
with a subcommand.
"""

from __future__ import annotations

import argparse
import sys

from cankar.corpus import cli as corpus_cli


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="cankar", description="CankarGTP pipeline CLI")
    stages = ap.add_subparsers(dest="stage", required=True)
    corpus_cli.register(stages.add_parser("corpus", help="Phase 1: corpus acquisition"))
    # future stages register here: tokenizer (Ph2), evals (Ph2.25), train (Ph3), pairs (Ph5)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
