# registry/reports/ - machine-owned, generated

Two report classes live here (marker line names the class):

- **drift-checked** (coverage-*.md, collisions.md): regenerated
  byte-identically by `cankar corpus report --all`; CI diff-checks them.
- **snapshot** (corpus-quality.md, near-duplicates.md): computed from
  gitignored data/ by `cankar corpus stats` / `cankar corpus dedup`;
  CI cannot regenerate them - do NOT fold them into `report --all` or
  the drift gate goes red.

Every file starts with a GENERATED marker. Hand edits are overwritten (and
fail CI for the drift-checked class). Human annotations belong in
../works/NOTES.md.
