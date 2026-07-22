# registry/datasets/ - committed provenance manifests

One manifest per generated shard/dataset (per stage subdir), written by the
generating command: git SHA, args, counts, content sha256, sanity band. This is
what makes "regenerate and diff" (ADR 0003) real - manifests in gitignored
data/ would prove nothing.
