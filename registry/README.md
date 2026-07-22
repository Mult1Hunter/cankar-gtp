# registry/ - committed ledgers (source of truth)

Everything git must remember about data that git does not hold (ADR 0004/0007):
`works/` - human-curated works registries (hand-editable, notes sacred);
`datasets/` - machine-appended provenance manifests for every shard;
`reports/` - generated coverage/collisions (drift-checked in CI, never edited);
`runs/` - arrives Phase 2 (one record per tokenizer/train/eval run).
