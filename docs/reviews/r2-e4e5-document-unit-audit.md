# R2-E4E5 DocumentUnit Semantic Audit

## Contract

The existing Stage 10.2.1 structure audit now includes `document_unit_audit` in its JSON report and DocumentUnit counts in its summary. The pipeline passes its in-memory Markdown to Audit; the historical four-argument Audit API remains usable for documents without DocumentUnits. Audit reads Canonical and rendered Markdown. It does not rerun discovery, coverage, Provider execution, or normalization.

For Canonical 1.1, Audit checks unique IDs, valid source/role/page/title/status/range/evidence fields using the existing Canonical validator. It additionally requires each anchor and proposal reference, every candidate reference, and a Provider-derived source reference linked by task ID. These are reference-chain checks; Audit does not reopen raw Provider outputs or verify OCR accuracy.

Each unit must have exactly one delimited Markdown marker with matching ID, anchor page, range status, span, and original `title_parts` in order. The marker must be near a matching source-page comment and marker pages must follow rendering order. The expected `PARTIAL` text says the complete extent is unknown; `RESOLVED` explicitly says coverage is nonexclusive. A marker cannot become a Markdown Section heading.

For content protection, Audit removes only the delimited DocumentUnit blocks, renders the same Canonical payload with an empty `document_units` list, and requires byte-identical Markdown. Existing Stage 6 → Canonical record ID/order, native paragraph authority, and fallback checks remain active. All Canonical base record fields must equal Stage 6 exactly; only the established `stage10_record_index` and `stage10_resolution` additions are excluded from that comparison. This protects table/text/provenance fields. The Canonical section list must equal the Stage 6 section list exactly, including IDs, titles, pages, and record references. Audit also rejects `document_id` ownership fields on records or sections and a top-level `section_parent_map`.

## Failure and allowed uncertainty

Audit returns `FAIL` for malformed or duplicated Canonical IDs, broken evidence links, missing/extra/duplicated markers, mismatched title/page/range/status text, a marker promoted to `#` heading, modified base Markdown, or inferred record/section ownership. Missing Markdown is a failure when units exist.

Audit accepts duplicate titles on different units, overlapping page ranges, `UNKNOWN` role, `PARTIAL` coverage, absent section/record parentage, and unresolved pages. Coverage is never treated as exclusive ownership.

## Existing samples

| Case | Canonical units | Markdown markers | Provenance checked | Range statuses | DocumentUnit audit | Overall audit |
|---|---:|---:|---:|---|---|---|
| case_003 | 5 | 5 | 5 | p27/p30/p36 PARTIAL; p29/p66 RESOLVED | PASS | PASS |
| case_004 | 2 | 2 | 2 | p83/p108 PARTIAL | PASS | PASS |

All marker titles equal the Canonical `title_parts` in their original order. Both samples pass the byte-identical base-Markdown comparison after marker removal. Their Canonical `sections`, `pages`, `records`, and `fallback_overlays` equal the existing historical result; no Provider was rerun and no historical artifact was overwritten. No DocumentUnit semantic issue was found in these two samples.

This audit cannot prove PDF truth or precise within-page ownership. It validates the published evidence chain and presentation against the available Canonical contract. Full record/section ownership remains unassigned.
