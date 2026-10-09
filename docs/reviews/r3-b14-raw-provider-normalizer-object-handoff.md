# R3-B14 RawProviderResult → Normalizer Object Handoff

## Original chain and actual contract

Provider adapters and persistent workers implement `Provider.execute(ProviderTask) -> RawProviderResult`. The frozen dataclass carries `provider`, `task_id`, `status`, an arbitrary `payload`, optional `markdown`, optional `elapsed_seconds`, and `warnings`. RapidOCR and PaddleOCR adapters produce in-process OCR text/geometry payloads; worker-backed MinerU, Marker and Docling return text plus paths/worker diagnostics from their own output files. Provider-owned Markdown/JSON/HTML/image reads remain within those adapters and are outside this phase.

`execute_provider_plan` already held the `RawProviderResult` in memory and passed it directly to `normalize_runtime_result(raw, task, result_path, manifest_path)`. The runtime adapter built the frozen task-result dict, wrote `provider_raw/<task_id>.json` and `provider_raw/runtime_manifest.json`, then called `normalize_prediction`. Previously, `normalize_one` opened the just-written raw task JSON through `load_json(result_path)`. Each of seven provider-specific normalizers also reopened the raw task JSON and runtime manifest to compute `source_artifacts.task_result_sha256` and `benchmark_manifest_sha256`. This was the remaining PDFFast-owned fresh write→read bus.

## New fresh path and preserved file path

The runtime adapter still writes both artifacts using the same `json.dumps` settings and trailing newline. It passes a local, JSON-wire-compatible dict derived from the **existing RawProviderResult** into `normalize_prediction(result_data=...)`, with SHA256 values computed from the exact strings that were written. The adapter does not reopen either artifact. The small wire-value conversion turns nested tuples into lists and Path/other non-JSON primitives into strings, matching the old JSON loader's values without a JSON dump/load roundtrip; the RawProviderResult and its payload remain untouched.

`normalize_one` now uses `result_data` when supplied and otherwise keeps its historical `load_json(result_path)` branch. Both paths enter the same `validate_task_result`, provider-specific adapter dispatch and `validate_canonical`. Each adapter uses the supplied known hashes for fresh task-result/manifest provenance, or hashes the files for standalone/replay calls. The original `normalize_prediction(manifest, manifest_path, task_map, provider, result_path)` call remains valid. No provider-specific text, spatial, block, table, formula, status, ranking, escalation, preflight, lifecycle, worker, or Stage 10/Audit algorithm changed.

Fresh reads of PDFFast's just-written raw task JSON = **0**; fresh reads of the runtime manifest solely for provenance SHA256 = **0**. Provider-specific `provider_raw_refs` or other source files may still be opened when the emitted evidence requires it. Those are Provider evidence inputs, not a write-back of the `RawProviderResult` task JSON. The raw task JSON, runtime manifest, selected files and indexes retain their paths and serializers.

## Parity and mutation evidence

The new tests intercept `Path.read_text` and `Path.open` for the fresh raw task JSON and runtime manifest while allowing writes. They reconstruct `RawProviderResult` from existing real Provider outputs without starting workers, then compare fresh object normalization to the legacy file normalization on the **same written artifact and path**. Object predictions are identical as Python dicts and as serialized JSON. The RawProviderResult is unchanged. Each fresh raw task JSON is byte-identical to its existing historical fixture.

The real-case test covers **all 147** available raw task results: case_002 1, case_003 54, case_004 92. For every task, object and file predictions match, prediction fields apart from relocation-dependent `source_artifacts` match the historical selected attempt, `provider_raw_refs` match, and the frozen executor's `_evaluate` acceptance/escalation triggers match the historical last attempt. The selected index closes exactly against the plan in all cases. case_003 retains two terminal unresolved tasks. Selected prediction and index writers in `fallback/executor.py` were not edited. Existing B11–B13 Stage 10 tests continue to establish Canonical/DocumentUnit/Markdown/render-manifest/Audit parity from the unchanged selected contract; no heavy Provider run was performed.

| Case | Plan / selected task closure | Terminal unresolved | Raw object/file normalization | Historical selected decision |
|---|---:|---:|---|---|
| case_002 | 1 / 1 | 0 | all identical | same |
| case_003 | 54 / 54 | 2 | all identical | same; five DocumentUnit anchors remain 27, 29, 30, 36, 66 downstream |
| case_004 | 92 / 92 | 0 | all identical | same |

Additional synthetic cases cover all seven adapter names and the distinct text-only, spatial OCR, explicit reading-block, HTML-table, formula, FAILED and TIMEOUT shapes. A nested tuple/Path case characterizes the old JSON-wire conversion and verifies object/file equality. Legacy file normalizer and seven-provider reference-bound normalizer parity tests remain in the full suite.

Relocating a raw fixture into `tmp_path` changes `source_artifacts.task_result`, `benchmark_manifest` and their content hashes by design; these are path/provenance metadata. The object and file calls within each test use the same new paths and are fully identical. The raw task JSON content itself matches the historical fixture bytes.

## Test results and remaining file buses

- New raw handoff tests: **19 passed**.
- Full `tests/unit tests/contracts tests/regression`: **311 passed, 20 skipped, 0 failed**. Passed increased by 19; the 20 reference-dependent skips are unchanged.
- Reference-bound (`PDFFAST_REFERENCE_ROOT=/Users/admin/Workspace/pdffast`, `PDFFAST_SAMPLE_PDF=/Users/admin/Workspace/pdffast/benchmark/samples/real/case_002.pdf`): **331 passed, 0 failed**.
- `git diff --check` is run at completion. Tests use `UV_CACHE_DIR=/private/tmp/pdffast-uv-cache uv run --no-sync pytest …` because the sandbox cannot initialize the default uv cache.

After this change, the previously identified formal PDFFast fresh-run object chain has **no remaining known PDFFast-owned intermediate JSON write→read dependency**. Original PDF/config/policy reads, Provider-owned files and retained artifact/replay interfaces still exist and are intentional. This is a bounded conclusion about the audited production chain, not a claim that the whole application performs no filesystem I/O.
