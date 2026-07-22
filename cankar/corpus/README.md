# cankar/corpus/ - Phase 1 corpus stage

Acquisition (wikivir.py, dlib.py), cleaning with calibrated guards (clean.py,
ocr_clean.py), works-registry logic (registry.py, seed.py, catalog.py),
reports (coverage.py), orchestration (ingest.py), CLI (cli.py - the only
argparse holder). Heuristics carry their calibration provenance in docstrings
and are pinned by tests/fixtures/corpus/ (ADR 0006).
