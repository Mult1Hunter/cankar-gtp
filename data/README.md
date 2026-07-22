# data/ - gitignored working data

Local shards and intermediates, mirrored by stage: corpus/, later tokenized/,
pairs/, export/. NOTHING here is ever tracked (structure test enforces, incl.
force-adds) except this file. Provenance lives in registry/datasets/;
re-creation is always: `cankar corpus ingest --all` + `crawl-dlib`.
