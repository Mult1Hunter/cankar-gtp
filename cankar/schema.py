"""Data contracts for corpus JSONL shards (validation ladder L2 — ADR 0003)."""

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
