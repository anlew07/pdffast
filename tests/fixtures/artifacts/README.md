# Artifact fixture provenance

All Phase 0 fixtures in this directory are synthetic. They were written to
exercise the migration comparator and contain no text, identifiers, images, or
metadata copied from a real applicant PDF.

| Fixture | Role | Schema/version |
|---|---|---|
| `reference.json` | Synthetic reference artifact with stable semantic fields and variable runtime metadata | Comparator fixture 1.0 |
| `candidate_runtime_only.json` | Same semantics with different approved runtime metadata and path roots | Comparator fixture 1.0 |
| `candidate_semantic_change.json` | Deliberate text change used to prove semantic drift is detected | Comparator fixture 1.0 |
| `reference.md` | Synthetic byte-comparison reference | Markdown fixture 1.0 |
| `candidate.md` | Deliberate whitespace change used to prove Markdown is not normalized | Markdown fixture 1.0 |

If a later fixture is copied from a reference artifact, this file must record
its exact source path, artifact schema/version, redaction status, and whether it
contains sensitive PDF content before that fixture is committed.
