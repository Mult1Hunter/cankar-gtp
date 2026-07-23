"""Data contracts for corpus JSONL shards (validation ladder L2 - ADR 0003)."""

from __future__ import annotations

import unicodedata

from pydantic import BaseModel, field_validator, model_validator


class CorpusDoc(BaseModel):
    """One document on one line of a corpus JSONL shard."""

    title: str
    url: str
    text: str
    n_chars: int
    source: str  # e.g. "wikivir", "wikipedia"
    author: str | None = None  # attribution for per-author stats (PD literature)

    @field_validator("text")
    @classmethod
    def text_is_nfc(cls, v: str) -> str:
        """NFC normalization is a project-wide invariant (č/š/ž NFD bugs)."""
        if not unicodedata.is_normalized("NFC", v):
            raise ValueError("text must be NFC-normalized (project invariant)")
        return v

    @model_validator(mode="after")
    def n_chars_matches_text(self) -> CorpusDoc:
        if self.n_chars != len(self.text):
            raise ValueError(f"n_chars={self.n_chars} != len(text)={len(self.text)}")
        return self


class ChunkDoc(BaseModel):
    """One training chunk of a corpus document (ADR 0012).

    Chunks carry their source doc's identity plus char spans into the
    original text: `text == doc.text[char_start:char_end]`, spans of a doc
    are adjacent and cover it, so plain concatenation reconstructs the doc
    byte-exact. Phase 2.25 holdout keys on (url, char span) - spans survive
    re-chunking, chunk_index does not. NFC is NOT re-validated here: a
    substring of NFC text can begin mid-grapheme; reconstruction is the
    integrity invariant for chunks.
    """

    title: str
    url: str
    text: str
    n_chars: int
    n_tokens: int  # encode_ordinary count, BOS excluded (row_capacity = T+1)
    source: str
    author: str | None = None
    chunk_index: int
    n_chunks: int
    char_start: int
    char_end: int

    @model_validator(mode="after")
    def spans_consistent(self) -> ChunkDoc:
        if self.n_chars != len(self.text):
            raise ValueError(f"n_chars={self.n_chars} != len(text)={len(self.text)}")
        if self.char_end - self.char_start != self.n_chars:
            raise ValueError(f"span [{self.char_start},{self.char_end}) != n_chars={self.n_chars}")
        if not 0 <= self.chunk_index < self.n_chunks:
            raise ValueError(f"chunk_index {self.chunk_index} outside n_chunks {self.n_chunks}")
        return self
