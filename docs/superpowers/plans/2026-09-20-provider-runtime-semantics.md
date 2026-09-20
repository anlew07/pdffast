# Provider Runtime Semantics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split benchmark/runtime enable semantics and reject any frozen runtime policy whose Provider closure is not fully runtime-enabled before execution starts.

**Architecture:** `configs/providers.json` becomes the six-instance production registry with explicit booleans. `pdffast.providers.registry` owns config validation and closure validation; the fallback executor invokes that validation before creating Providers or artifacts. Provider packages remain optional and no installation is part of this plan.

**Tech Stack:** Python 3.12, JSON, pytest, existing dataclass/Protocol Provider interfaces.

## Global Constraints

- Do not modify `configs/frozen/stage9_route_candidates_prod_v001.json`.
- Do not install Provider packages, create virtualenvs, initialize models, or download artifacts.
- Runtime resolution reads only `runtime_enabled`; benchmark selection reads only `benchmark_enabled`.
- Production closure contains exactly six approved Provider instances.
- PDFFast Core must not import FastAPI, UploadFile, HTTP framework types, or Celery.

---

### Task 1: Production configuration and Registry semantics

**Files:**
- Modify: `configs/providers.json`
- Modify: `pdffast/providers/registry.py`
- Modify: `tests/contracts/test_frozen_configs.py`
- Modify: `tests/unit/test_provider_registry.py`

**Interfaces:**
- Produces: `PRODUCTION_PROVIDER_NAMES`, `ProviderRegistry.create(name, config)`, and explicit `runtime_enabled` validation.

- [ ] Replace old Registry tests with failing tests proving six-instance scope, PP-Structure exclusion, benchmark-disabled runtime resolution, and runtime-disabled rejection.
- [ ] Run focused tests and confirm failures are caused by old `enabled` semantics and seven-kind scope.
- [ ] Update the production JSON to six entries; replace every `enabled` with `runtime_enabled` and `benchmark_enabled` using the old benchmark default as the latter value.
- [ ] Update Registry constants and resolution logic minimally until focused tests pass.
- [ ] Recompute only the `configs/providers.json` contract checksum; assert the frozen route-candidate checksum remains unchanged.

### Task 2: Pre-execution closure validation

**Files:**
- Modify: `pdffast/providers/registry.py`
- Modify: `pdffast/fallback/executor.py`
- Modify: `tests/unit/test_provider_registry.py`
- Modify: `tests/unit/test_fallback_executor.py`

**Interfaces:**
- Produces: `validate_runtime_provider_closure(policy, provider_configs) -> frozenset[str]`.
- Consumes: Stage 9.6.3 `tasks[].provider_chain[].provider` and production Provider config mapping.

- [ ] Write failing tests for missing, runtime-disabled, and unsupported policy Providers.
- [ ] Write a failing executor test whose Registry sentinel would fail if resolution is reached; assert closure validation fails first.
- [ ] Implement whole-policy validation with named configuration errors.
- [ ] Call validation at the top of `execute_fallback`, before output directories and state-machine waves.
- [ ] Update existing fake configs to explicit runtime/benchmark fields and run focused tests green.

### Task 3: Environment, cache, and enterprise boundary documentation

**Files:**
- Create: `docs/PROVIDER_RUNTIME_ENVIRONMENTS.md`
- Modify: `tests/contracts/test_production_import_boundaries.py`

**Interfaces:**
- Documents: four approved V2 environment locations, shared cache paths/variables, offline verification order, and service-to-Core dependency direction.

- [ ] Add a failing package import-boundary test for `fastapi`, `starlette`, `celery`, and HTTP adapter types in Core.
- [ ] Extend the import-boundary scanner without adding service dependencies.
- [ ] Write the environment document using audited package versions and cache locations; mark installation and model download as not performed.
- [ ] Assert the document contains all six production instances, all four environments, cache reuse rules, and the import/preflight/cache/smoke order.

### Task 4: Full verification and commits

**Files:**
- Verify all files above.

**Interfaces:**
- Produces: a clean repository whose configuration, tests, and docs agree on the same six-Provider closure.

- [ ] Run focused Registry/executor/import-boundary tests.
- [ ] Run the default suite.
- [ ] Run reference-bound frozen-config and source-baseline tests.
- [ ] Verify the frozen route-candidate SHA-256 remains `0d999777e130de54ff25248c02cf39ae37e9fe7c5ef9231650aa3304008772d3`.
- [ ] Run `git diff --check`, inspect `git status`, and commit cohesive changes without installing dependencies.

