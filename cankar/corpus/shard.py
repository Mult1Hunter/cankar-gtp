"""Shard IO - the shared write and read sides of every corpus source (ADR 0008
rule of two: wikivir + dlib + wikipedia all turn CorpusDocs into a JSONL shard,
tally counts, and emit a committed manifest; stats/dedup/seed all read shards
back). Acquisition differs per source (API pagination vs dump streaming), so
only the shard IO is shared here.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import TextIO

from cankar.core.manifest import ShardManifest, git_sha, sha256_of, utc_now_iso, write_manifest
from cankar.core.paths import dataset_manifest
from cankar.core.schema import CorpusDoc


def read_shard(path: Path) -> Iterator[dict]:
    """Stream a shard's docs without materializing it (the wikipedia shard is
    65M words - a list would defeat the single-pass consumers)."""
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


class ShardWriter:
    """Streams CorpusDocs to a JSONL shard and writes its provenance manifest.

    Use as a context manager so the file closes before the manifest hashes it:

        with ShardWriter(out, source="wikipedia", script="cankar corpus ...") as w:
            for doc in docs:
                w.write(doc)
        # manifest written on exit; counts available as w.n_docs / w.n_words
    """

    def __init__(
        self,
        out: Path,
        *,
        source: str,
        script: str,
        args: dict[str, object],
        expected_band: tuple[int, int] | None = None,
    ):
        self.out = out
        self.source = source
        self.script = script
        self.args = args
        self.expected_band = expected_band
        self.n_docs = 0
        self.n_chars = 0
        self.n_words = 0
        # callers with a skip taxonomy set this before the context exits; it is
        # written into the manifest (ADR 0004 amendment - the committed drop record)
        self.skip_counts: dict[str, int] | None = None
        self._fh: TextIO | None = None

    def __enter__(self) -> ShardWriter:
        self.out.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self.out.open("w", encoding="utf-8")
        return self

    def write(self, doc: CorpusDoc) -> None:
        if self._fh is None:
            raise RuntimeError("ShardWriter.write called outside its context manager")
        self._fh.write(doc.model_dump_json() + "\n")
        self.n_docs += 1
        self.n_chars += doc.n_chars
        self.n_words += len(doc.text.split())

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        if self._fh is not None:
            self._fh.close()
        if exc_type is not None:
            return  # no provenance manifest for a failed/partial run
        manifest = ShardManifest(
            source=self.source,
            script=self.script,
            git_sha=git_sha(),
            retrieved_at=utc_now_iso(),
            args=self.args,
            n_docs=self.n_docs,
            n_chars=self.n_chars,
            n_words=self.n_words,
            sha256=sha256_of(self.out),
            expected_band_words=self.expected_band,
            skip_counts=self.skip_counts,
        )
        write_manifest(manifest, dataset_manifest("corpus", self.out.stem))
