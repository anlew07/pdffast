# R3-B13 Audit Object Input Convergence

## Scope and former production reads

The only fresh production Audit file reads were in `pdffast/pipeline/runner.py:run_stage10`: `_load(a.normalized_flow)` and `_load(a.quality_gate)` immediately before `audit(...)`. `_load` uses `Path.read_text` and `json.loads`. The Audit core in `pdffast/audit/structure_boundary.py` already accepts four Python dicts plus Markdown, then forwards them to `_stage10_audit.py:audit`. It has no additional production file loader. The standalone `_stage10_audit.py:main` CLI separately loads normalized flow, Quality, Canonical and render manifest JSON, and optionally Markdown; that file entry remains unchanged.

The Audit core uses Native `source_file`, `records` and `sections` to check backbone identity/order, paragraph authority and rendered record accounting. It uses Quality `source_file`, `pages[*].decision` (or `summary.pages_by_decision`) and `pages[*].non_text_assessment.regions` for page routes, region provenance, fallback and unresolved accounting. Canonical was already passed as an in-memory dict, render manifest as the Renderer-returned dict, and Markdown as the Renderer-returned string. DocumentUnit marker checks consume Canonical and Markdown, not another Native/Quality file.

## New fresh input path

`run_stage10` now passes `text_flow.normalized_flow` and `quality_report.data` directly to the existing `audit(...)` call when those objects are supplied by `run_core_pipeline`. The Canonical object, render manifest and Markdown calls are unchanged. The original normalized-flow and Quality writers still run before Stage 10. No Audit algorithm, validation rule, threshold, warning rule, or output serializer was modified. `ParseResult.from_pipeline` still receives the Audit dict from the runtime result, without reopening audit.json.

When `run_stage10(context)` is called without runtime objects, its `_load` fallback still hydrates normalized flow and Quality from files, then calls the **same** Audit core. The standalone Audit CLI and its file inputs remain intact. Fresh normalized-flow reads = **0** and fresh Quality reads = **0**. Combined with B11–B12, the fresh Stage 10 and Audit path has zero reads of section alignment, normalized flow, Quality, provider plan, selected index and selected prediction files. File outputs and compatibility readers remain available for regression, inspection and future replay.

## Parity and read-only checks

The case_002/003/004 test first runs the legacy full-file Stage 10 entry, then runs the fresh object entry with existing real execution artifacts hydrated once. During the fresh run, `Path.read_text` and `Path.open` raise on any attempt to read alignment, normalized flow, Quality, provider plan, selected index or selected prediction files. Thus the test covers the Audit reads as well as the Canonical/DocumentUnit reads already protected by B12.

An Audit spy confirms exact object identity: Native input is `TextFlowResult.normalized_flow`, Quality input is `QualityReport.data`, Canonical input is the same object returned by Stage 10, and Markdown is the returned string. It compares Native, Quality, Canonical and render manifest before/after the Audit call and detects no mutation. The broader test also compares upstream alignment, CapabilityPlan and selection objects before/after Stage 10, and verifies source artifact hashes are unchanged.

On identical input/output paths, object and file runs produced byte-identical `result/document.json`, `result/document.md`, `render_manifest.json` and `result/audit.json` in all three cases. Hence Audit status/checks/warnings, record and fallback accounting, provenance checks, and DocumentUnit marker checks are unchanged. The same regression suite tests missing-marker and altered-section/table failures, so the PASS/FAIL boundaries remain covered. The normalized-flow, Quality and Audit artifacts remain written at their prior paths/schema/serialization; this phase changes no artifact writer.

| Case | Tasks | Terminal unresolved | DocumentUnit anchors | Object/file Audit |
|---|---:|---:|---|---|
| case_002 | 1 | 0 | As in file baseline | byte-identical |
| case_003 | 54 | 2 | 27, 29, 30, 36, 66 | byte-identical; five markers retained |
| case_004 | 92 | 0 | As in file baseline | byte-identical |

## Tests and remaining runtime file bus

- Focused Stage 10/Audit handoff and DocumentUnit Audit regression: **5 passed** after the new read interception and identity checks.
- Full `tests/unit tests/contracts tests/regression`: **292 passed, 20 skipped, 0 failed**. No test was added; existing B12 tests were strengthened, so the passed and skipped counts are unchanged.
- Reference-bound (`PDFFAST_REFERENCE_ROOT=/Users/admin/Workspace/pdffast`, `PDFFAST_SAMPLE_PDF=/Users/admin/Workspace/pdffast/benchmark/samples/real/case_002.pdf`): **312 passed, 0 failed**.
- `git diff --check` is run at completion. Tests use the existing virtualenv via `UV_CACHE_DIR=/private/tmp/pdffast-uv-cache uv run --no-sync pytest …` because the sandbox denies initialization of the default uv cache.

The remaining known PDFFast-owned runtime file bus is **`RawProviderResult → provider_raw/<task>.json → Normalizer`**. Provider adapters, Normalizer, Selection and Provider output artifacts are not changed by R3-B13.
