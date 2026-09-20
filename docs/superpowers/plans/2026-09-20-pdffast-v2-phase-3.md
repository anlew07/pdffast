# PDFFast v2 Phase 3 Provider Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate production Provider execution, prediction normalization, and fallback wave semantics without importing benchmark selection or evaluation logic.

**Architecture:** Define a small Provider lifecycle protocol and registry, keep local heavy engines behind isolated persistent workers, and migrate the Stage 9.5.1 normalizer as an independent sealed module. The executor consumes the frozen runtime policy and calls Provider plus normalizer interfaces; deterministic fake Providers prove wave/escalation/terminal behavior before any real model is installed.

**Tech Stack:** Python 3.12, dataclasses/protocols, subprocess JSONL workers, pytest; optional pinned RapidOCR/PaddleOCR, Docling, MinerU, and Marker environments only after consolidated approval.

## Global Constraints

- Production runtime must not import GT, evaluator, holdout, route benchmark selection, Surya, Tesseract, or generic CLI adapters.
- Supported Provider scope is RapidOCR, PaddleOCR mobile/VL/PP-Structure, Docling, MinerU, and Marker.
- Core/fake tests must run without optional Provider packages, model downloads, keys, or network access.
- Provider initialization, execution, normalization, timeout, and close failures remain distinguishable in attempt provenance.
- `close()` is idempotent; isolated worker termination is mandatory after error or timeout.
- No cache, concurrency, provider-order, acceptance-rule, or artifact-format optimization in this phase.

---

### Task 1: Provider protocol, task/result types, and registry

**Files:**
- Create: `pdffast/providers/__init__.py`
- Create: `pdffast/providers/base.py`
- Create: `pdffast/providers/registry.py`
- Test: `tests/unit/test_provider_registry.py`
- Modify: `tests/contracts/test_production_import_boundaries.py`

**Interfaces:**
- Produces: `ProviderPreflight`, `ProviderTask`, `RawProviderResult`, `Provider` protocol, and `ProviderRegistry.create(name, config)`.
- Registry accepts only the seven approved adapter kinds (`rapidocr`, `paddleocr_text`, `paddleocr_vl`, `pp_structure_v3`, `docling_worker`, `mineru_worker`, `marker_worker`) covering the six approved Provider families, and raises a named configuration error for disabled/unknown kinds.

- [ ] Write tests for lifecycle shape, exact supported-kind mapping, disabled providers, unknown kinds, and no eager optional imports.
- [ ] Run the focused test and confirm RED because `pdffast.providers` is absent.
- [ ] Implement the minimal types and lazy registry factories.
- [ ] Run focused and default suites; commit `feat: add provider runtime contracts`.

### Task 2: Prediction normalizer migration

**Files:**
- Create: `pdffast/providers/normalization.py`
- Create: `tests/fixtures/providers/` static raw-result fixtures for all approved Provider kinds
- Create: `tests/regression/test_prediction_normalizer_parity.py`

**Interfaces:**
- Consumes: raw result JSON, Provider name, task metadata, and manifest path.
- Produces: `normalize_prediction(...) -> dict[str, Any]` and identical canonical JSON artifacts.

- [ ] Extract representative existing raw outputs into content-minimal, non-sensitive fixtures for RapidOCR, PaddleOCR mobile/VL/PP-Structure, Docling, MinerU, and Marker.
- [ ] Write a parameterized old-script versus new-API byte parity test.
- [ ] Run RED because `pdffast.providers.normalization` is absent.
- [ ] Transplant Stage 9.5.1 algorithms without Tesseract paths or CLI parsing; preserve validation and serialization.
- [ ] Run focused/default suites; commit `feat: migrate prediction normalizer`.

### Task 3: Fake Provider executor state machine

**Files:**
- Create: `pdffast/fallback/executor.py`
- Create: `tests/fakes/providers.py`
- Create: `tests/unit/test_fallback_executor.py`

**Interfaces:**
- Consumes: provider plan, runtime policy, Provider registry, prediction normalizer, and output directory.
- Produces: production execution manifest, selected prediction index, selected canonical files, attempts, and logs.

- [ ] Write deterministic tests for first-attempt accept, escalation, provider exception, normalization failure, terminal source preservation, pipeline failure, batch grouping, and idempotent close.
- [ ] Run RED because the executor API is absent.
- [ ] Migrate Stage 9.8 wave, acceptance, selection, hashing, and terminal semantics against injected interfaces.
- [ ] Assert no subprocess benchmark script or GT/evaluation input is accepted by the public executor API.
- [ ] Run focused/default suites; commit `feat: migrate fallback executor state machine`.

### Task 4: Approved Provider adapters and isolated worker protocol

**Files:**
- Create: `pdffast/providers/rapidocr.py`
- Create: `pdffast/providers/paddleocr.py`
- Create: `pdffast/providers/workers.py`
- Create: `pdffast/providers/docling.py`
- Create: `pdffast/providers/mineru.py`
- Create: `pdffast/providers/marker.py`
- Create: `tests/unit/test_provider_lifecycle.py`
- Create: `tests/provider/test_provider_contracts.py`

**Interfaces:**
- Each adapter implements `preflight`, `initialize`, `execute`, and idempotent `close`.
- Worker protocol uses one JSON request/response per line with explicit init, execute, close, timeout, and structured error messages.

- [ ] Write dependency-free lifecycle tests with fake engine/worker factories and verify RED.
- [ ] Extract only production adapter/worker behavior from Stage 9.3; omit benchmark sampling, metrics, summaries, Surya, Tesseract, and generic CLI.
- [ ] Run dependency-free lifecycle/default tests.
- [ ] Pause once with a consolidated approval list before creating environments, installing packages, or downloading models.
- [ ] After approval, run marked real-provider preflight/one-task contracts and record explicit PASS/SKIP per Provider.
- [ ] Commit `feat: add approved provider adapters`.

### Task 5: Phase 3 integration and documentation

**Files:**
- Create: `tests/regression/test_phase3_executor_parity.py`
- Modify: `README.md`
- Modify: `docs/MIGRATION_PLAN.md`

**Interfaces:**
- Runs reference Stage 9.8 and candidate executor from the same provider plan/policy/task inputs, using seeded raw/canonical results where deterministic real inference is unavailable.

- [ ] Compare production manifest, selected index, selected canonical files, attempts, warnings, provider selection, and terminal status.
- [ ] Run default suite, reference-bound suite, source baseline, frozen configs, import-boundary contracts, and `git diff --check`.
- [ ] Document optional Provider environment commands and preflight status without claiming skipped Providers passed.
- [ ] Mark Phase 3 complete only when executor/normalizer parity and approved Provider contract criteria are satisfied.
- [ ] Commit `test: verify phase 3 provider runtime`.
