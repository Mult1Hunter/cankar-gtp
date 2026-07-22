"""ShardWriter - the shared write side of every corpus source (ADR 0008 rule of
two: wikivir + dlib + wikipedia all turn CorpusDocs into a JSONL shard, tally
counts, and emit a committed manifest). Acquisition differs per source (API
pagination vs dump streaming), so only the write side is shared here.
"""

from __future__ import annotations

from pathlib import Path
from typing import TextIO

from cankar.core.manifest import ShardManifest, git_sha, sha256_of, utc_now_iso, write_manifest
from cankar.core.paths import dataset_manifest
from cankar.core.schema import CorpusDoc


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
        self._fh: TextIO | None = None

    def __enter__(self) -> ShardWriter:
        self.out.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self.out.open("w", encoding="utf-8")
        return self

    def write(self, doc: CorpusDoc) -> None:
        assert self._fh is not None, "ShardWriter used outside its context manager"
        self._fh.write(doc.model_dump_json() + "\n")
        self.n_docs += 1
        self.n_chars += doc.n_chars
        self.n_words += len(doc.text.split())

    def __exit__(self, *exc: object) -> None:
        assert self._fh is not None
        self._fh.close()
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
        )
        write_manifest(manifest, dataset_manifest("corpus", self.out.stem))
