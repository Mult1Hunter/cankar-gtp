# cankar/core/ - cross-stage contracts

Schemas (CorpusDoc), provenance manifests, path policy (`paths.py` - the only
place artifact locations are defined), future prompt loading. Imports NO other
cankar module (import-linter enforced). If it knows about a specific stage, it
does not belong here.
