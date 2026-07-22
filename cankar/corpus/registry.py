"""Works registry - the source of truth for known works and where we got them.

One JSONL file per author under registry/ (committed, diffable). Every document
that enters the corpus must map to a registry entry; every known-but-unusable
item (manuscripts, in-copyright editions) is recorded, never silently dropped.
See ADR 0004.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from pydantic import BaseModel, field_validator

SOURCE_STATUSES = {
    "ingested",  # text is in a corpus shard
    "candidate",  # exists at the source, text not fetched (e.g. wikivir already covers it)
    "skipped-quality",  # fetched but failed the OCR quality gate
    "skipped-manuscript",  # handwriting scan, OCR unusable by policy
    "skipped-rights",  # not public domain at this source
    "missing",  # known work, no usable source found yet
}

_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
_WS_RE = re.compile(r"\s+")


def normalize_title(title: str) -> str:
    """Matching key: NFC, casefold, punctuation to spaces, diacritics KEPT."""
    t = unicodedata.normalize("NFC", title).casefold()
    t = _PUNCT_RE.sub(" ", t)
    return _WS_RE.sub(" ", t).strip()


def normalize_for_author(title: str, author: str) -> str:
    """Also strip a trailing disambiguator naming the author: "Ada (Ivan Cankar)" -> "ada"."""
    surname = author.split()[-1].casefold()
    t = unicodedata.normalize("NFC", title)
    t = re.sub(
        r"\s*\(([^)]*)\)\s*$",
        lambda m: "" if surname in m.group(1).casefold() else m.group(0),
        t,
    )
    return normalize_title(t)


def slugify(title: str) -> str:
    t = normalize_title(title)
    t = unicodedata.normalize("NFKD", t)
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    return _WS_RE.sub("-", t).strip("-")


class SourceRef(BaseModel):
    source: str  # "wikivir" | "dlib" | future sources
    id: str  # wikivir page title or dLib URN
    status: str
    year: int | None = None  # publication year of this edition, if known
    note: str = ""

    @field_validator("status")
    @classmethod
    def status_known(cls, v: str) -> str:
        if v not in SOURCE_STATUSES:
            raise ValueError(f"unknown status {v!r}; allowed: {sorted(SOURCE_STATUSES)}")
        return v


class WorkRecord(BaseModel):
    work_id: str
    title: str  # canonical display title
    author: str
    year: int | None = None  # first known publication year
    genre: str | None = None
    flags: list[str] = []  # e.g. ["prevod"] for Cankar's translations of others
    aliases: list[str] = []  # alternate titles ("gl." cross-references)
    sources: list[SourceRef] = []
    notes: str = ""  # human notes - tooling must never clobber this


class Registry:
    """In-memory registry for one author, keyed by normalized title."""

    def __init__(self, author: str, works: list[WorkRecord] | None = None):
        self.author = author
        self.works: dict[str, WorkRecord] = {}
        self._by_norm: dict[str, str] = {}  # normalized title/alias -> work_id
        for w in works or []:
            self._index(w)

    def _index(self, work: WorkRecord) -> None:
        self.works[work.work_id] = work
        self._by_norm[normalize_title(work.title)] = work.work_id
        for a in work.aliases:
            self._by_norm.setdefault(normalize_title(a), work.work_id)

    def find(self, title: str) -> WorkRecord | None:
        norm = normalize_for_author(title, self.author)
        wid = self._by_norm.get(norm)
        return self.works.get(wid) if wid else None

    def upsert(
        self,
        title: str,
        year: int | None = None,
        genre: str | None = None,
        flags: list[str] | None = None,
    ) -> WorkRecord:
        existing = self.find(title)
        if existing:
            if year and not existing.year:
                existing.year = year
            if genre and not existing.genre:
                existing.genre = genre
            for f in flags or []:
                if f not in existing.flags:
                    existing.flags.append(f)
            return existing
        work = WorkRecord(
            work_id=slugify(normalize_for_author(title, self.author)),
            title=title,
            author=self.author,
            year=year,
            genre=genre,
            flags=flags or [],
        )
        self._index(work)
        return work

    def add_alias(self, work: WorkRecord, alias: str) -> None:
        if alias not in work.aliases:
            work.aliases.append(alias)
        self._by_norm.setdefault(normalize_title(alias), work.work_id)

    def add_source(self, work: WorkRecord, ref: SourceRef) -> None:
        """Idempotent by (source, id); an upgrade to `ingested` always wins."""
        for existing in work.sources:
            if existing.source == ref.source and existing.id == ref.id:
                if ref.status == "ingested" or existing.status != "ingested":
                    existing.status = ref.status
                if ref.year:
                    existing.year = ref.year
                if ref.note:
                    existing.note = ref.note
                return
        work.sources.append(ref)

    # --- persistence (sorted -> stable diffs) ---

    @classmethod
    def load(cls, path: Path, author: str) -> Registry:
        works = [
            WorkRecord.model_validate_json(line) for line in path.read_text().splitlines() if line
        ]
        return cls(author, works)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            self.works[wid].model_dump_json(exclude_defaults=False) for wid in sorted(self.works)
        ]
        path.write_text("\n".join(lines) + "\n")

    # --- validation ---

    def validate(self, min_year: int | None = None, max_year: int | None = None) -> list[str]:
        problems: list[str] = []
        seen_norm: dict[str, str] = {}
        for wid, w in self.works.items():
            if wid != w.work_id:
                problems.append(f"{wid}: key/work_id mismatch")
            norm = normalize_title(w.title)
            if norm in seen_norm and seen_norm[norm] != wid:
                problems.append(f"duplicate normalized title {norm!r}: {wid} vs {seen_norm[norm]}")
            seen_norm[norm] = wid
            for s in w.sources:
                if s.year and min_year and max_year and not (min_year <= s.year <= max_year):
                    problems.append(
                        f"{wid}: source {s.source}:{s.id} year {s.year} outside "
                        f"plausible range {min_year}-{max_year}"
                    )
        return problems
