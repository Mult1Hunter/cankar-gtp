#!/usr/bin/env python3
"""dLib.si (National Library digital archive) machinery - EDM metadata, URN
enumeration, OCR gates, authorship checks.

Manuscripts are recorded and skipped; wikivir-ingested works are covered
without fetching text (hand transcription beats OCR).

Terms-of-use compliance (dlib.si/Help.aspx, checked 2026-07): only records
carrying dLib's public-domain rights mark are ingested (everything else is
recorded as skipped-rights); "Digitalna knjiznica Slovenije - dLib.si" is
credited as source in README "Data sources". Polite crawl: 0.5s delay, UA
with contact.

Verified dLib API surface (2026-07):
- results HTML pages carry URN:NBN:SI:<TYPE>-<ID> identifiers (100/page)
- per-URN EDM JSON at /URN.../EDM/JSON (title, year, language, types, rights,
  stream links); rights PD marker: creativecommons.org/publicdomain/mark
- TEXT streams need a session cookie (visit a details page first) + referer,
  and are usually windows-1250 encoded (cankar.ocr_clean handles both)

The original registry-gated `crawl-dlib` flow is retired (ADR 0004 amendment 2
declared its gating the bug class; `cankar corpus reconcile-dlib` is its
superset - audit + authorship-checked pull). This module keeps the shared dLib
machinery: EDM parsing, URN enumeration, the OCR gate chain, and the layered
authorship check.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from urllib.parse import quote

from cankar.core.http import PoliteSession
from cankar.corpus.ocr_clean import decode_stream, ocr_clean

logger = logging.getLogger(__name__)

BASE = "https://www.dlib.si"
EARLY_NOISE_MAX = 10  # ocr_clean early_noise gate; calibrated on the first dLib audit
DEFAULT_MIN_ALPHA = 0.84  # alpha_ratio floor; calibrated on the first dLib audit
DEFAULT_MIN_CHARS = 400  # shortest acceptable cleaned text


URN_RE = re.compile(r"URN:NBN:SI:[A-Z]+-[A-Z0-9]+")
PD_MARKER = "publicdomain"
YEAR_RE = re.compile(r"\d{4}")


def as_list(v: object) -> list:
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def txt(v: object) -> str | None:
    """EDM values appear as plain strings or {'#text': ..., '@xml:lang': ...}."""
    if isinstance(v, str):
        return v
    if isinstance(v, dict):
        return v.get("#text")
    return None


def enumerate_urns(session: PoliteSession, contributor: str) -> list[str]:
    """All URNs from the paged results listing."""
    urns: list[str] = []
    seen: set[str] = set()
    page = 1
    while True:
        q = quote(f"'contributor={contributor}'")
        url = f"{BASE}/results/?query={q}&pageSize=100&page={page}"
        found = URN_RE.findall(session.get(url).text)
        new = [u for u in dict.fromkeys(found) if u not in seen]
        if not new:
            return urns
        seen.update(new)
        urns += new
        page += 1


@dataclass(frozen=True)
class EdmRecord:
    """Parsed dLib EDM metadata for one URN (ADR 0008: typed, immutable)."""

    title: str
    year: int | None
    types: frozenset[str]
    langs: frozenset[str]
    people: frozenset[str]  # creators + contributors merged (back-compat)
    creators: frozenset[str]  # dc:creator only - the authorship claim
    rights: str
    text_url: str | None
    is_part_of: str | None


def parse_edm(data: dict) -> EdmRecord:
    rdf = data.get("edm:RDF", {})
    cho = rdf.get("edm:ProvidedCHO", {})
    agg = rdf.get("ore:Aggregation", {})

    title = (txt(as_list(cho.get("dc:title"))[0]) or "").rstrip("|").strip()
    year_m = YEAR_RE.search(str(txt(as_list(cho.get("dcterms:issued"))[0]) or ""))
    types = {(txt(t) or "").casefold() for t in as_list(cho.get("dc:type"))}
    langs = {(txt(v) or "").casefold() for v in as_list(cho.get("dc:language"))}
    people = {
        (txt(p) or "") for key in ("dc:contributor", "dc:creator") for p in as_list(cho.get(key))
    }
    creators = {(txt(p) or "") for p in as_list(cho.get("dc:creator"))}
    rights = (as_list(agg.get("edm:rights"))[0] or {}).get("@rdf:resource", "") if agg else ""
    text_url = next(
        (
            wr.get("@rdf:about")
            for wr in as_list(rdf.get("edm:WebResource"))
            if str(wr.get("@rdf:about", "")).endswith("/TEXT")
        ),
        None,
    )
    is_part_of = next(
        (txt(p) for p in as_list(cho.get("dcterms:isPartOf")) if txt(p)),
        None,
    )
    return EdmRecord(
        title=title,
        year=int(year_m.group(0)) if year_m else None,
        types=frozenset(types),
        langs=frozenset(langs),
        people=frozenset(people),
        creators=frozenset(creators),
        rights=rights,
        text_url=text_url,
        is_part_of=is_part_of,
    )


def clean_and_gate(
    raw: bytes, *, min_alpha: float = DEFAULT_MIN_ALPHA, min_chars: int = DEFAULT_MIN_CHARS
) -> tuple[str | None, str | None]:
    """OCR-clean a TEXT stream and apply the calibrated quality gates.
    Returns (text, None) on pass, (None, reason) on fail - one place holds the
    gate sequence so crawl and reconcile can never drift apart."""
    text, metrics = ocr_clean(decode_stream(raw))
    if metrics["early_noise"] > EARLY_NOISE_MAX:
        return None, f"severe opening corruption (early_noise={metrics['early_noise']})"
    if metrics["alpha_ratio"] < min_alpha or metrics["n_chars"] < min_chars:
        return None, f"alpha={metrics['alpha_ratio']} chars={metrics['n_chars']}"
    return text, None


# title-embedded attribution: "Napisal A. Askerc" etc. names the true author
_ATTRIB_RE = re.compile(r"(napisal|spisal|zložil)", re.IGNORECASE)
# memorial/tribute titles are ABOUT the person, not by them
_MEMORIAL_RE = re.compile(r"^spominu\b|\bv spomin\b", re.IGNORECASE)


def is_by_author(meta: EdmRecord, query_contributor: str) -> bool:
    """Layered authorship check, calibrated on real contamination the corpus-qa
    audit caught in the first gap-fill pull (all three committed as fixtures):

    1. dc:creator is the authorship claim - when present, it decides, and it
       must match the full queried name ("Cankar, Ivan"), not the bare surname:
       Izidor Cankar edited Ivan's collected works, and a surname match would
       accept him. A trailing qualifier ("Cankar, Ivan (1876-1918)") still
       matches via prefix. (Caught: Gregorcic's collected poems where Cankar
       is only dc:contributor.)
    2. dLib often omits dc:creator on journal records, so fall back to the
       merged people set by surname - but reject titles carrying an
       attribution phrase without the author's surname after it (caught:
       'Lirske in epske poezije; Napisal A. Askerc') and memorial-pattern
       titles (caught: 'Spominu Ivana Cankarja' - a tribute ABOUT the author).
    Residual risk (accepted, documented): a work by someone else where dLib
    lists only the author as contributor AND the title carries no attribution.
    """
    query = query_contributor.casefold()
    surname = query.split(",")[0].strip()
    if meta.creators:
        return any(c.casefold().startswith(query) for c in meta.creators)
    if not any(surname in p.casefold() for p in meta.people):
        return False
    m = _ATTRIB_RE.search(meta.title)
    if m and surname not in meta.title[m.start() :].casefold():
        return False
    if _MEMORIAL_RE.search(meta.title):
        return False
    return True
