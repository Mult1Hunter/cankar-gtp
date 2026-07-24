# Analyst notes - human-owned (never generated)

Resolution annotations for cross-author collisions listed in
`registry/reports/collisions.md`; consumed by the merge/dedupe stage.

## 2026-07-22

- Rokovnjaci (jurcic + kersnik): SAME WORK - Jurcic began it, Kersnik completed
  it after his death. Keep once at merge; attribute jointly.
- Tugomer (jurcic + levstik): two versions of the same tragedy (Levstik's
  rewrite of Jurcic's text) - verify whether the Wikivir pages differ before
  dedupe.
- By/about essays (e.g. "Josip Stritar (Ivan Tavcar)") are excluded at crawl
  time by the attribution guard; they appear only in the essayist's shard.
- zivljenje-in-smrt-petra-novljana: dLib source year 2013 is a modern e-book
  reissue of the PD text; content verified as Cankar's - year anomaly
  acknowledged (also noted in the work record itself).

## 2026-07 gap-fill contamination purge (corpus-qa finding)

Removed three `dlib-discovered` entries that were never Cankar works - the
original discovery pass filtered on the merged creator+contributor set, and
dLib lists Cankar as *contributor* (subject/editor) on records BY others:

- `Izbrane pesmi| za stoletnico pesnikovega rojstva 1844-1944` (DOC-IWN6782U):
  Simon Gregorcic's collected poems (dc:creator = Gregorcic)
- `Lirske in epske poezije; Napisal A. Askerc` (DOC-AYWISGCW): Askerc's poetry,
  attribution in the title itself
- `Spominu Ivana Cankarja| (1876-1918)` (DOC-CRK1R8WE): memorial collection
  ABOUT Cankar by Zupancic, Lah, Kveder et al.

Fix class: reconcile's `is_by_author` now checks dc:creator first, plus
title-attribution and memorial guards (real cases committed as fixtures).
Remaining `dlib-discovered` entries are dormant candidates - any future pull
re-verifies authorship at classify time; a human sweep of the discovered set
is still worth doing before the merge stage.

## 2026-07 about-Cankar misattribution purge (holdout-audit finding, ADR 0014)

The ADR 0013 holdout audit found texts crawled into the cankar shard but
written by others, carrying author="Ivan Cankar". A full-corpus sweep (genitive
title + bare person-name + reading the text) enumerated the class - 5 records,
now flagged `not-by-author` and excluded at merge:

- `iz-prvih-spominov-na-ivana-cankarja`, `nekaj-mladostnih-spominov-na-ivana-cankarja`:
  memoirs by Vera Albreht (Pionir 1948/49, 1962) - about Cankar, and in
  copyright (Albreht d. 1982). Longer/shorter variants of one memoir; the merge
  dedup missed them (Jaccard 0.17 - a rewrite, not a near-dup).
- `kulturni-pomen-ivana-cankarja`: a critic's essay about Cankar, author
  unidentified.
- `vera-albreht`, `izidor-cankar`: Wikivir bibliography pages mis-crawled into
  the cankar shard; already gate-dropped, flagged to clear the false `ingested`
  record.

Only the first three were in the merged Cankar slice (the rest gate-dropped).
The genitive sweep alone was leaky (missed the two bare-name bibliography
pages), so enumeration used three signals, not one.

Hygiene follow-up (not done here): `pismo-josipa-murna-ivanu-cankarju-marec-1898`
is a letter BY Murn - already correctly re-attributed to Josip Murn in the
merged corpus by the collision table, so NOT flagged (that would drop his
letter). Its cankar.jsonl record is a stray; move it to murn.jsonl in a future
registry-hygiene pass.

## 2026-07 parallel-identity merge (design-review finding)

The same discovery pass had also upserted 27 verbatim dLib titles whose
pipe/semicolon head names an existing canonical work ('Hlapci| drama v petih
aktih', 'Crtice; Majska noc', 'Na klancu; Spisal Ivan Cankar', ...). These
parallel identities let the gap-fill pull re-ingest 19 editions of works
already ingested from Wikivir (MinHash caught only 5 - OCR noise depresses
Jaccard on the worst copies; registry identity caught the rest). Merged each
into its canonical work (verbatim title kept as alias, refs kept as
candidates); `match_work` now segment-splits on `[:;|]` head-first, so the
class cannot recur. Verified empirically: a text probe from 'Crtice; Ponocni
spomini' appears verbatim inside the wikivir Crtice doc - the subparts are
duplicates, not new texts.
