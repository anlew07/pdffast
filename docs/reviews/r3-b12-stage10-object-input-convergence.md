# R3-B12 Stage 10 Remaining Object Input Convergence

## Scope and original read points

Fresh production now hands existing in-memory results to Stage 10 and its Canonical/DocumentUnit calculations. This phase changes input transport only. Provider execution, selected-result writing, Native/Quality/Capability writers, Canonical merge rules, Renderer and Audit implementations remain unchanged. The previous selected prediction object handoff from R3-B11 remains intact.

Before this change, `canonical/_stage10_builder.py:build_document` loaded `normalized_text_flow.json`, `quality_gate.json` and `provider_plan.json`, then hashed each file for Canonical `inputs`. `canonical/document_units.py:resolve_document_units_from_artifacts` loaded `section_alignment.json` and normalized flow again. Its selected-prediction loader was already bypassed by B11. `pipeline/runner.py:run_stage10` still calls `_load(normalized_flow)` and `_load(quality_gate)` **for Audit**; those two Audit reads are intentionally outside B12.

## File fields → existing runtime objects

| Former input | Actual Stage 10 use | Existing runtime source |
|---|---|---|
| Section alignment | Reconciliation preview consumes `sections`, `pages`, `unresolved_regions` and source metadata; coverage also checks `page_count`. | The dict returned by `run_section_discovery`. That dict is written unchanged as `section_alignment.json`. |
| Normalized flow | Canonical validates source/page/schema, indexes `records`, `page_index`, `sections`, and retains Native provenance. Reconciliation uses `page_index` for heading ownership and proposals. | `TextFlowResult.normalized_flow`, the same dict passed to the Stage 6 JSON writer; no serialization-only fields are added. |
| Quality | Canonical uses page decisions/routes, non-text region assessments, source/page/schema and related fallback metadata. | `QualityReport.data`, the same dict passed to the Quality JSON writer. |
| Provider plan | Canonical uses task IDs/types/pages, source IDs/bboxes, capability route, Stage 8 decision/route/gate state, route hints, input-image provenance and source/page/schema. | **`CapabilityPlan.data`** from `create_capability_plan`; it is written as `provider_plan.json`. `ProviderExecutionPlan` is the later frozen execution policy and does not replace this Canonical input. |

## New fresh object path and compatibility path

`run_core_pipeline` retains `section_alignment`, `text_flow_result`, `quality_report` and `capability_plan` until Stage 10, and passes them alongside the existing `ProviderExecutionResult`. `run_stage10` gives the alignment and normalized flow to DocumentUnit reconciliation; it gives normalized flow, Quality and CapabilityPlan data to Canonical. The object path supplies the original dicts directly. Reconciliation creates its own preview data; Canonical copies records and output metadata as before. No upstream object is modified.

When no object inputs are supplied, `run_stage10(context)`, `canonical.builder.build_document(...)` and `resolve_document_units_from_artifacts(...)` retain their historical file behavior. Both paths enter the same reconciliation and Canonical merge algorithms. The fresh path does not require the four just-written files to hydrate semantic inputs, though the files are still emitted and their paths retained as provenance. Audit remains file-driven for normalized flow and Quality; Stage 10's **Canonical and DocumentUnit portion** has zero reads of all four files. R3-B11's selected index and selected prediction reads remain zero. The old standalone file entry still reads every input it needs and produces the same result.

Canonical's `inputs` includes SHA256 of normalized flow, Quality and provider plan. In the fresh path those hashes are calculated from `json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")`, matching the three existing writers exactly. The selected index hash continues to use B11's unchanged serializer, including its trailing newline. This preserves Canonical provenance without reopening files.

## Read interception, mutation and parity

The new test loads existing case_002/003/004 artifacts once to represent the already-computed runtime objects, executes the legacy file path, then executes the fresh object path. It intercepts `Path.read_text` and `Path.open` for alignment, flow, Quality, provider plan, selected index and every selected prediction file. During the object path, it permits only the two known `runner._load` calls that supply Audit with flow and Quality; every other read raises. Thus the observed fresh Canonical/DocumentUnit read count for all six categories is **0**, while the known Audit reads remain visible and unmodified.

The test compares bytes of `result/document.json`, `result/document.md`, `render_manifest.json` and `result/audit.json` on identical input/output paths; all are byte-identical between object and file entry. It also compares in-memory Canonical, Markdown and Audit results, verifies none of the five shared runtime inputs or selected wrappers/index were mutated, and verifies SHA256 of all existing source artifacts is unchanged. Writer implementations and selected-file formats were not changed. The test reuses existing Provider outputs and does not start heavy Provider workers.

| Case | Expected tasks | Selected tasks | Terminal unresolved | Missing/extra | Canonical/DocumentUnit/Renderer/Audit |
|---|---:|---:|---:|---:|---|
| case_002 | 1 | 1 | 0 | 0/0 | byte-identical object/file output |
| case_003 | 54 | 54 | 2 | 0/0 | byte-identical object/file output; five anchors at pages 27, 29, 30, 36, 66 |
| case_004 | 92 | 92 | 0 | 0/0 | byte-identical object/file output |

Task closure checks still run inside the existing Canonical builder; no expected/selected task accounting changed. The case_003 two terminal unresolved tasks, document boundaries, route metadata, source references and Provider provenance are covered by the byte comparison. No Canonical, Renderer or Audit algorithm was changed. The unchanged writers continue to emit section alignment, normalized flow, Quality, provider plan and selected artifacts at the same paths/schema/serialization. The tests' source SHA checks establish that these already-existing inputs were not changed by either Stage 10 path; the full producer algorithms were not rerun for this parity exercise.

## Tests and remaining file buses

- Focused B12 + B11 handoff tests: **8 passed**.
- Full `tests/unit tests/contracts tests/regression`: **292 passed, 20 skipped, 0 failed**.
- Reference-bound (`PDFFAST_REFERENCE_ROOT=/Users/admin/Workspace/pdffast`, `PDFFAST_SAMPLE_PDF=/Users/admin/Workspace/pdffast/benchmark/samples/real/case_002.pdf`): **312 passed, 0 failed**.
- Three new B12 tests account for the passed-count increase; skip count stayed at 20 without reference and 0 reference-bound.
- `git diff --check` passed. Because the sandbox cannot initialize the default uv cache, tests used `UV_CACHE_DIR=/private/tmp/pdffast-uv-cache uv run --no-sync pytest …` with the existing virtualenv.

Remaining runtime file buses: (1) `RawProviderResult → provider_raw/<task>.json → Normalizer`; (2) `runner._load(normalized_flow)` and `runner._load(quality_gate)` for Audit. Neither is changed here. All Stage 10 input artifacts remain available for diagnostics, regression, independent file invocation and future replay; this phase does not implement public resume/reuseExisting.
