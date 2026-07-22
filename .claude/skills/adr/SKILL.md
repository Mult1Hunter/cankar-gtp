---
name: adr
description: Scaffold a new ADR in docs/decisions/ — numbering, template matching ADR 0001, cross-linking. Use when a non-obvious design decision gets made.
---

# New ADR

1. **Number:** next after the highest `NNNN-*.md` in `docs/decisions/`
   (zero-padded to 4 digits).
2. **Filename:** `NNNN-kebab-case-title.md`.
3. **Template** (match ADR 0001's structure):

   ```markdown
   # ADR NNNN — <title>

   **Status:** accepted · YYYY-MM

   ## Context

   <the forces: what problem, which options existed>

   ## Decision

   <what was chosen, in one or two sentences>

   ## Rationale

   <bulleted whys, including known costs knowingly accepted>

   ## Consequences

   <what this commits us to / what gets harder>
   ```

4. Keep it under ~35 lines. One decision per ADR; a changed decision gets a new
   ADR that marks the old one `superseded by NNNN`.
5. If the decision changes a rule in CLAUDE.md or ROADMAP.md, update those files
   in the same commit.
