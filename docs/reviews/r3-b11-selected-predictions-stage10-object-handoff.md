# R3-B11 Selected Predictions → Stage 10 Object Handoff

## Scope and baseline

This phase changes only the fresh production handoff from Provider selection to Stage 10. The frozen starting baseline was 284 passed / 20 skipped without reference and 304 passed reference-bound. Existing uncommitted work from earlier phases was preserved. Provider execution, normalization, selection decisions, Canonical merge, Renderer, and Audit algorithms were not changed.

## 1–5. Previous data chain and read points

`Provider.execute` returns `RawProviderResult`; `normalize_runtime_result` returns a canonical prediction `dict`. `execute_provider_plan` evaluates that dict in memory, keeps attempts and `selected_canonical`, and builds one complete selected wrapper per task. It writes each wrapper through the existing `_write_json` function, builds and writes `selected_prediction_index.json`, then returns `ProviderExecutionResult(manifest, selected_index, selected_predictions)`. The returned index and wrapper list are the exact in-memory sources of those artifacts. The writer and serialization code were not changed.

Previously, `run_core_pipeline` held that result but called `run_stage10(context)` without it. `canonical/_stage10_builder.py:build_document` loaded the selected index with `load_json` and each `<task_id>.json` wrapper from the selected directory. Separately, `canonical/document_units.py:resolve_document_units_from_artifacts` called `diagnose_recovered_heading_candidates`, which loaded the same index and wrappers again. Both branches therefore used fresh selected artifacts as a runtime file bus.

## 6–8. New object handoff and read count

`run_core_pipeline` now calls `run_stage10(context, selection=production)`. The Stage 10 path passes the **same** `selection.selected_index` mapping and `selection.selected_predictions` list to both DocumentUnit reconciliation and the Canonical builder. The heading extractor receives the original wrappers plus a separate task-ID-to-file-reference map; it does not add `prediction_reference` to or otherwise mutate the wrappers. Canonical builds a task-ID index of the same wrapper objects and continues through the existing validation/merge implementation.

For fresh production Stage 10, selected index JSON reads = **0** and selected prediction JSON reads = **0**. The in-memory index hash is computed from the exact existing `_write_json` serialization (`json.dumps(..., ensure_ascii=False, indent=2) + "\n"`), preserving the Canonical `inputs.selected_prediction_index.sha256` value without reopening that file. Native section alignment, normalized flow, Quality, and provider plan continue to be file inputs by design for this phase.

`run_stage10(context)` without `selection` is unchanged as a file compatibility entry. `canonical.builder.build_document(...)` and `resolve_document_units_from_artifacts(...)` likewise retain their file paths when selected objects are omitted. This phase does not add resume/reuseExisting support to the public parser.

## 9–13. Contracts and artifacts

The existing Canonical `validate_inputs` still checks source/page agreement, Stage 9 index shape, declared item count, equality of provider-plan/index/wrapper task sets, duplicate plan IDs, wrapper metadata agreement, `ground_truth_used=False`, no silent `pipeline_failure`, terminal REGION preserve shape, and non-terminal selected canonical with nonempty text. The object path also rejects duplicate or missing wrapper IDs before this validator. It does not reinterpret an absent prediction as blank text: terminal REGION tasks retain `selected_canonical=None`; case_003 retains two terminal unresolved tasks. No selection/ranking/escalation decision code changed.

The same wrapper retains task, provider, route, attempt, selected canonical, diagnostics, source artifact references, and other prediction fields. The Canonical builder's existing `compact_canonical` and overlay merge rules run unchanged. Recovered heading candidates retain the historical `prediction_reference` path through an auxiliary lookup; source references still come from the selected prediction itself. The selected index, per-task selected JSON files, production manifest, and provider source artifacts continue to be written at the same paths by the same writer. The object path does not modify the shared selection data.

## 14–19. Real-artifact parity, no heavy Provider startup

The new test hydrates real existing execution results for case_002/003/004 once, then calls the old file Stage 10 path and the new object path against identical input paths. During the object call, `Path.read_text` and `Path.open` raise if either selected index or any selected prediction file is read. The test compares byte content of `result/document.json`, `result/document.md`, `render_manifest.json`, and `result/audit.json`; it also compares in-memory Canonical/Markdown/Audit objects and confirms selected object values and source file SHA256 hashes are unchanged. Thus object and file outputs, including sections, pages, records, overlays, tables/images references and Provider provenance, are byte-identical for all three cases. Because the same output paths are reused, path metadata is covered by the byte comparisons rather than excluded.

| Case | Expected plan tasks | Selected index/wrappers | Terminal unresolved | Missing/extra | Closure | Object/file outputs |
|---|---:|---:|---:|---:|---|---|
| case_002 | 1 | 1/1 | 0 | 0/0 | pass | byte-identical |
| case_003 | 54 | 54/54 | 2 | 0/0 | pass | byte-identical |
| case_004 | 92 | 92/92 | 0 | 0/0 | pass | byte-identical |

The case_003 object result retains DocumentUnit anchors at pages **27, 29, 30, 36, 66**; Canonical and rendered document marker parity follows from the byte comparison. A missing selected wrapper is rejected by the object path, protecting task closure. The legacy file API is exercised before each object call. These tests reuse existing Provider outputs and do not start heavy Providers. They verify source selected artifact hashes are unchanged; the production selected artifact writer itself is untouched.

## 20–21. Test results

- Focused new handoff + fallback executor + case_003 Canonical regression: **15 passed**.
- Full `tests/unit tests/contracts tests/regression`: **289 passed, 20 skipped, 0 failed**.
- Reference-bound, with `PDFFAST_REFERENCE_ROOT=/Users/admin/Workspace/pdffast` and `PDFFAST_SAMPLE_PDF=/Users/admin/Workspace/pdffast/benchmark/samples/real/case_002.pdf`: **309 passed, 0 failed**.
- Passed count increased by five new tests. Skip count stayed at 20 without reference; reference-bound has no skips.
- The sandbox denied initialization of the default uv cache. Tests were run with `UV_CACHE_DIR=/private/tmp/pdffast-uv-cache uv run --no-sync pytest …` against the existing project virtualenv. No dependency was changed.

## 22. Remaining runtime file buses

1. `RawProviderResult → provider_raw/<task>.json → Normalizer` remains unchanged.
2. Stage 10 still reopens section alignment, normalized flow, Quality, and provider plan. Audit still reopens normalized flow and Quality. These are outside R3-B11.
3. selected prediction index/files remain persistence, inspection, regression, provenance, and file compatibility artifacts, but are no longer read to continue a fresh production Stage 10 calculation.
