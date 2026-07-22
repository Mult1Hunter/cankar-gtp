"""Parse Wikivir author catalog pages into registry entries.

Two page shapes exist (both seed the works registry):
- author index ("Ivan Cankar"): {{Avtor}} infobox + genre sections with
  "* [[Title]], 1899, 2. izdaja 1902" entries
- alphabetical list ("Seznam del Ivana Cankarja"): letter-grouped
  "*[[Title]]" entries, "gl. [[X]]" cross-references, "(prevod)" flags
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from cankar.corpus.registry import WorkFlag

ENTRY_RE = re.compile(r"^\*+\s*\[\[([^\]|]+)(?:\|[^\]]*)?\]\](.*)$")
SECTION_RE = re.compile(r"^=+\s*([^=]+?)\s*=+\s*$")
YEAR_RE = re.compile(r",\s*(\d{4})")
GL_RE = re.compile(r"\bgl\.\s*\[\[([^\]|]+)(?:\|[^\]]*)?\]\]")
AVTOR_FIELD_RE = re.compile(r"^\|\s*(leto_rojstva|leto_smrti)\s*=\s*(\d{4})", re.MULTILINE)

# sections that do not contain works
NON_WORK_SECTIONS = {"dela", "glej tudi", "viri", "zunanje povezave"}


@dataclass
class CatalogEntry:
    title: str  # wikilink target = actual Wikivir page name
    year: int | None = None
    genre: str | None = None
    alias_of: str | None = None  # set for "gl. [[X]]" cross-reference lines
    flags: list[WorkFlag] = field(default_factory=list)


@dataclass
class AuthorMeta:
    birth_year: int | None = None
    death_year: int | None = None


def parse_catalog(wikitext: str) -> tuple[list[CatalogEntry], AuthorMeta]:
    meta = AuthorMeta()
    for m in AVTOR_FIELD_RE.finditer(wikitext):
        if m.group(1) == "leto_rojstva":
            meta.birth_year = int(m.group(2))
        else:
            meta.death_year = int(m.group(2))

    entries: list[CatalogEntry] = []
    section: str | None = None
    for line in wikitext.splitlines():
        sec = SECTION_RE.match(line)
        if sec:
            name = sec.group(1).strip().casefold()
            section = None if name in NON_WORK_SECTIONS else sec.group(1).strip()
            continue
        entry = ENTRY_RE.match(line)
        if not entry:
            continue
        title, tail = entry.group(1).strip(), entry.group(2)
        gl = GL_RE.search(tail)
        year_match = YEAR_RE.search(tail)
        flags = [WorkFlag.PREVOD] if "(prevod)" in tail or title.endswith("(prevod)") else []
        entries.append(
            CatalogEntry(
                title=title,
                year=int(year_match.group(1)) if year_match else None,
                genre=section,
                alias_of=gl.group(1).strip() if gl else None,
                flags=flags,
            )
        )
    return entries, meta
