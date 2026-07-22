"""Ingest a Slovenian Wikipedia pages-articles dump into a corpus shard.

General-Slovene pretraining layer (ROADMAP Phase 1). Streams the bz2 XML dump
with stdlib bz2 + xml.etree.iterparse - no new deps. Wikipedia does NOT enter
the works registry (that is authored literary works only; ADR 0004 as amended);
provenance lives in the committed dataset manifest. "Never silently dropped"
(ADR 0004) is honored by counts, not per-item triage: every skip reason is
tallied and recorded in the manifest.

Verified against the real slwiki dump (2026-07): the XML declares a default
namespace, so every tag arrives namespace-qualified and MUST be matched on its
localname; clearing each <page> is not enough - its emptied stub stays under the
retained root, so the root is cleared periodically to keep memory flat over
~198k articles.
"""

from __future__ import annotations

import bz2
import logging
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from xml.etree.ElementTree import Element, iterparse

from cankar.core.manifest import sha256_of
from cankar.core.schema import CorpusDoc
from cankar.corpus.clean import clean_wikitext, is_index_title
from cankar.corpus.registry import Source
from cankar.corpus.shard import ShardWriter
from cankar.corpus.wikipedia_clean import is_disambiguation, wikipedia_preclean

logger = logging.getLogger(__name__)

LICENSE = "CC BY-SA 4.0"
ROOT_CLEAR_EVERY = 1000  # pages between root.clear() calls (memory vs overhead)


@dataclass
class WikipediaStats:
    """Per-reason ingestion counters (ADR 0008; ADR 0004 'never silently
    dropped' honored by counts, not per-item triage)."""

    docs: int = 0
    words: int = 0
    non_ns0: int = 0
    redirect: int = 0
    disambig: int = 0
    list_page: int = 0
    stub_min_chars: int = 0
    empty_text: int = 0

    def as_dict(self) -> dict[str, int]:
        return {k: v for k, v in vars(self).items()}


def _local(tag: str) -> str:
    """Strip the {namespace} qualifier iterparse attaches to every tag."""
    return tag.rsplit("}", 1)[-1]


@dataclass
class _Page:
    title: str
    ns: str
    is_redirect: bool
    text: str


def _iter_pages(dump: Path) -> Iterator[_Page]:
    """Stream pages from the bz2 dump with flat memory (root cleared periodically)."""
    root: Element | None = None
    seen = 0
    with bz2.open(dump, "rb") as fh:
        for event, elem in iterparse(fh, events=("start", "end")):
            if event == "start" and root is None:
                root = elem
                continue
            if event == "end" and _local(elem.tag) == "page":
                rev = elem.find("{*}revision")
                yield _Page(
                    title=elem.findtext("{*}title") or "",
                    ns=elem.findtext("{*}ns") or "",
                    is_redirect=elem.find("{*}redirect") is not None,
                    text=(rev.findtext("{*}text") if rev is not None else "") or "",
                )
                elem.clear()
                seen += 1
                if root is not None and seen % ROOT_CLEAR_EVERY == 0:
                    root.clear()


def ingest(dump: Path, out: Path, *, min_chars: int = 400) -> WikipediaStats:
    """Stream the dump, skip non-prose classes, clean articles, write the shard."""
    stats = WikipediaStats()
    args: dict[str, object] = {
        "dump_filename": dump.name,
        "dump_sha256": sha256_of(dump),
        "dump_mtime": datetime.fromtimestamp(dump.stat().st_mtime, UTC).date().isoformat(),
        "license": LICENSE,
        "min_chars": min_chars,
    }
    writer = ShardWriter(
        out, source=Source.WIKIPEDIA, script="cankar corpus ingest-wikipedia", args=args
    )
    with writer:
        for i, page in enumerate(_iter_pages(dump), 1):
            if i % 20000 == 0:
                logger.info(f"  scanned {i} pages, kept {stats.docs}")
            if page.ns != "0":
                stats.non_ns0 += 1
                continue
            if page.is_redirect:
                stats.redirect += 1
                continue
            if is_index_title(page.title) or page.title.startswith("Seznam "):
                stats.list_page += 1
                continue
            if is_disambiguation(page.text):
                stats.disambig += 1
                continue
            text = clean_wikitext(wikipedia_preclean(page.text))
            if not text:
                stats.empty_text += 1
                continue
            if len(text) < min_chars:
                stats.stub_min_chars += 1
                continue
            writer.write(
                CorpusDoc(
                    title=page.title,
                    url=f"https://sl.wikipedia.org/wiki/{page.title.replace(' ', '_')}",
                    text=text,
                    n_chars=len(text),
                    source=Source.WIKIPEDIA,
                    author=None,
                )
            )
    stats.docs, stats.words = writer.n_docs, writer.n_words
    logger.info(f"wrote {out}: {stats.docs} docs, {stats.words:,} words")
    for reason, n in stats.as_dict().items():
        logger.info(f"  {reason}: {n}")
    return stats
