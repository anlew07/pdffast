# PDFFast Output Governance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans or superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hide development-stage output behind a stable result boundary while preserving existing parsing behavior and internal artifacts.

**Architecture:** Add a small runtime-output layer around the existing pipeline. The parser selects `minimal`, `diagnostic`, or `full`; the runner redirects stage/provider output to a run-local log and publishes canonical outputs under `result/`. Existing Stage files and paths remain internal compatibility artifacts.

**Tech Stack:** Python 3.12, pathlib, dataclasses, contextlib, logging, pytest.

## Global Constraints

- Do not modify `configs/frozen/stage9_route_candidates_prod_v001.json`.
- Do not change parsing algorithms, thresholds, Provider escalation order, model caches, or environment boundaries.
- Core must remain independent of FastAPI, Celery, UploadFile, and HTTP request/response types.
- `minimal` keeps internal files in the run directory in this first implementation; it does not delete data.
- Public documentation and docstrings are Chinese-first; code identifiers and API names remain English.

### Task 1: Runtime configuration and output contracts

**Files:**
- Create: `pdffast/config.py`
- Create: `pdffast/errors.py`
- Create: `pdffast/runtime.py`
- Modify: `pdffast/pipeline/context.py`
- Modify: `pdffast/parser.py`
- Test: `tests/unit/test_output_governance.py`

**Interfaces:**
- `OutputMode = Literal["minimal", "diagnostic", "full"]`
- `ParserConfig` stores `project_root`, `output_root`, `output_mode`, `capture_output`, and existing pipeline defaults.
- `RuntimeLog` exposes `path: Path` and a context manager that redirects stdout/stderr and Python logging to that path.
- `PDFFastError` is the base public exception; `ConfigurationError` and `ParseExecutionError` carry `run_dir` and optional `log_path`.

- [x] Write tests for output-mode validation, default values, and public exception fields.
- [x] Run the focused tests and verify they fail before implementation.
- [x] Implement the dataclasses and validation without importing any service framework.
- [x] Extend `PipelineContext.create()` with output mode and capture settings while preserving existing call defaults.
- [x] Update `PDFFastParser` to accept `ParserConfig` or compatible keyword arguments and retain mapping compatibility.
- [x] Run the focused tests and `tests/contracts/test_production_import_boundaries.py`.

### Task 2: Capture Stage output and publish stable results

**Files:**
- Modify: `pdffast/pipeline/runner.py`
- Modify: `pdffast/pipeline/artifacts.py`
- Modify: `pdffast/parser.py`
- Test: `tests/unit/test_output_governance.py`

**Interfaces:**
- `ArtifactPaths.result_dir`, `result_document`, `result_markdown`, `result_audit`, and `result_manifest` are stable public paths.
- `run_core_pipeline()` captures output around native Stage and Provider execution when enabled.
- `run_stage10()` writes the existing artifacts and publishes semantically identical result copies.

- [x] Add failing tests proving parser calls do not leak Stage summaries to stdout.
- [x] Add failing tests for `result/` paths and captured `diagnostics/logs/pipeline.log`.
- [x] Implement the smallest runner context wrapper around existing calls; do not edit every legacy `print()`.
- [x] Publish canonical, Markdown, audit, and combined manifest files under `result/`.
- [x] Convert unexpected execution failures to `ParseExecutionError` with log/run paths while preserving cause.
- [x] Run focused tests and existing Phase 4 unit tests.

### Task 3: Diagnostic and full retention behavior

**Files:**
- Modify: `pdffast/pipeline/artifacts.py`
- Modify: `pdffast/pipeline/runner.py`
- Create: `docs/OUTPUT_MODES_ZH.md`
- Test: `tests/unit/test_output_governance.py`

**Interfaces:**
- `minimal` exposes only result paths in the public result mapping.
- `diagnostic` additionally exposes log and internal artifact paths.
- `full` exposes the complete legacy artifact mapping for migration/debugging.

- [x] Add tests for all three public result shapes and mode-specific metadata.
- [x] Implement mode-aware result metadata without deleting any files.
- [x] Document when to use each mode and the no-deletion first-release policy in Chinese.
- [x] Run focused and package tests.

### Task 4: Public documentation and full verification

**Files:**
- Modify: `README.md`
- Create: `docs/QUICKSTART_ZH.md`
- Create: `docs/INTEGRATION_ZH.md`
- Create: `docs/TROUBLESHOOTING_ZH.md`
- Modify: `tests/unit/test_package.py`

**Interfaces:**
- Documentation uses `from pdffast import PDFFastParser` and `result.markdown`/mapping-compatible access.
- Examples do not require FastAPI, Celery, or direct Stage imports.

- [x] Add tests that compile the documented minimal Python example.
- [x] Rewrite README as a Chinese-first tool-project guide while retaining technical names and test commands.
- [x] Add integration and troubleshooting guidance for logs, output modes, Provider availability, and cache reuse.
- [x] Run `pytest tests/unit tests/contracts tests/regression` and the reference-bound suite when its environment is available.
- [x] Run `compileall` and `git diff --check`; verify Frozen route SHA is unchanged.
