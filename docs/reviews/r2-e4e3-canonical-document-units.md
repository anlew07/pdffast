# R2-E4E3 Canonical DocumentUnit Integration

## Schema change

Canonical `schema_version` changes from `1.0` to `1.1`; builder `version` changes from `0.1.5` to `0.1.6`. The top-level payload gains `document_units: []`. Existing `sections`, `pages`, `records`, and `fallback_overlays` retain their structure and meaning. `ParseResult` remains an outer wrapper around the Canonical payload and is unchanged.

Each published unit contains `document_id`, `role`, `source`, `anchor` (`page`, ordered original `title_parts`, `anchor_ref`, `candidate_refs`, `evidence_refs`, `bbox_coordinate_space`), `anchor_status`, `range_status`, `page_range` (`start_page`, `end_page`), and `coverage_evidence_refs`. Candidate and evidence references point back to the admitted proposal, selected Provider prediction, and its source; no raw Provider result is copied into Canonical. Internal stop reasons and rejected candidates remain diagnostic data.

Only admitted `ANCHOR_CONFIRMED` recovered units with `PARTIAL` or `RESOLVED` coverage enter this first version. The provisional Primary unit is omitted because its range and section membership are unconfirmed. `document_units` is **not** an exhaustive partition of the PDF. `source` and `role` are distinct; the recovered case_003 units have role `UNKNOWN`.

`page_range` is a continuous span of confirmed intersection between a DocumentUnit and physical pages. It does not assert exclusive page or record ownership; overlaps are valid. For `PARTIAL`, the reported span is only the confirmed portion, with an unknown extent beyond it. For `RESOLVED`, both ends are closed by the current page-relation evidence, but record ownership remains undetermined.

No `record.document_id` or `section.document_id` is assigned. Neither record ownership nor section parentage is inferred from page overlap. Renderer and Audit semantics are unchanged; Markdown does not render DocumentUnits.

## Existing case_003 evidence

The existing E4B → E4C → E4D → admission → coverage chain produces five admitted recovered units:

| Anchor page | Confirmed span | Range status | Role |
|---|---|---|---|
| 27 | 27–27 | PARTIAL | UNKNOWN |
| 29 | 29–29 | RESOLVED | UNKNOWN |
| 30 | 30–30 | PARTIAL | UNKNOWN |
| 36 | 36–36 | PARTIAL | UNKNOWN |
| 66 | 66–66 | RESOLVED | UNKNOWN |

The Primary placeholder is absent. The existing case_003 `sections`, `pages`, `records`, `fallback_overlays`, and summary compare equal to the rebuilt payload; rendered `document.md` is byte identical. Existing sample artifacts were read only, and no Provider was rerun.

The existing case_004 artifacts also complete the same evidence chain. They admit two recovered anchors: p83 and p108, both with `PARTIAL` 83–83 and 108–108 spans. These are derived from its actual selected predictions; no units were fabricated to fill pages.

## Compatibility

Consumers that read only the existing fields can continue to use those fields. A strict validator that accepts only schema `1.0` or rejects unknown fields must be updated for `1.1`. The new DocumentUnit validator checks the additive field; the current Renderer validator still accepts the historical `1.0` reference payload and the new `1.1` payload. Downstream consumers must not treat a missing unit or a `PARTIAL` span as proof that no document exists elsewhere.
