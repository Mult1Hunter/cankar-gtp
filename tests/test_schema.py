"""Contract tests for cankar.schema and cankar.manifest (validation ladder L2)."""

import json
import unicodedata
from pathlib import Path

import pytest
from pydantic import ValidationError

from cankar.manifest import ShardManifest, manifest_path, sha256_of, write_manifest
from cankar.schema import CorpusDoc


def make_doc(**overrides: object) -> CorpusDoc:
    base: dict[str, object] = {
        "title": "Noč",
        "url": "https://sl.wikisource.org/wiki/No%C4%8D",
        "text": "Vzdramil se je nenadoma.",
        "n_chars": 24,
        "source": "wikivir",
        "author": "Ivan Cankar",
    }
    base.update(overrides)
    return CorpusDoc(**base)  # type: ignore[arg-type]


def test_valid_doc_roundtrips() -> None:
    doc = make_doc()
    again = CorpusDoc.model_validate_json(doc.model_dump_json())
    assert again == doc


def test_nfd_text_rejected() -> None:
    nfd = unicodedata.normalize("NFD", "čaša")
    with pytest.raises(ValidationError, match="NFC"):
        make_doc(text=nfd, n_chars=len(nfd))


def test_wrong_n_chars_rejected() -> None:
    with pytest.raises(ValidationError, match="n_chars"):
        make_doc(n_chars=999)


def test_unicode_not_ascii_escaped() -> None:
    """č/š/ž must land in JSONL as UTF-8, not \\u escapes."""
    doc = make_doc(text="čšž", n_chars=3)
    assert "čšž" in doc.model_dump_json()


def test_manifest_roundtrip(tmp_path: Path) -> None:
    shard = tmp_path / "x.jsonl"
    shard.write_text('{"a":1}\n')
    m = ShardManifest(
        source="wikivir",
        script="scripts/crawl_wikivir.py",
        git_sha="abc1234",
        retrieved_at="2026-07-22T00:00:00+00:00",
        args={"category": ["Kategorija:Ivan Cankar"]},
        n_docs=1,
        n_chars=7,
        n_words=1,
        sha256=sha256_of(shard),
        expected_band_words=(1_500_000, 3_000_000),
    )
    out = write_manifest(shard, m)
    assert out == manifest_path(shard) == tmp_path / "x.manifest.json"
    loaded = ShardManifest.model_validate(json.loads(out.read_text()))
    assert loaded == m
