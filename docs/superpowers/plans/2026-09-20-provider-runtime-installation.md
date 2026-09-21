# Provider Runtime Installation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Install and validate the six frozen production Providers in four V2-owned Python environments without downloading models already present in shared user caches.

**Architecture:** Install one Provider family at a time and gate the next family on import, preflight, cache discovery, one-task execution, canonical normalization, lifecycle cleanup where applicable, and regression verification. In-process RapidOCR/Paddle Providers live in `.venv`; MinerU, Marker, and Docling remain persistent subprocess workers in dedicated `.venv-*` environments.

**Tech Stack:** Python 3.12 arm64, uv-managed virtual environments, RapidOCR 3.9.2, ONNX Runtime 1.30.0, PaddleOCR 3.6.0, PaddlePaddle 3.2.1, PaddleX 3.6.1, MinerU 3.4.5, Marker PDF 2.0.0, Docling 2.127.0, pytest.

## Global Constraints

- Do not modify `configs/frozen/stage9_route_candidates_prod_v001.json`, algorithm thresholds, or Provider escalation order.
- Do not install benchmark-only Providers, PP-Structure, Tesseract, or standalone Surya.
- V2 environments must not import from old-project virtualenvs.
- Reuse `/Users/admin/.paddlex` and `/Users/admin/.cache/huggingface`; never copy models into Git.
- Do not permit an implicit model download. Stop and report an absent production artifact.
- Run each Provider family through the required verification and commit before starting the next family.
- Do not run a complete real PDF after all six smoke tests.

---

### Task 1: Main environment RapidOCR

**Files:**
- Modify: `.venv/` (Git-ignored environment)
- Create/Update: `docs/PROVIDER_RUNTIME_VALIDATION.md`

**Interfaces:**
- Produces: runtime-resolvable `rapidocr_ch_light` and a CanonicalPrediction from one existing input image.

- [x] Install exactly `rapidocr==3.9.2` and `onnxruntime==1.30.0` with uv into `.venv`.
- [x] Prove RapidOCR ONNX weights are package data and no separate model download occurred.
- [x] Run import, Registry resolve, preflight, one-image execution, normalization, and close.
- [x] Run Provider, Registry, executor, default, and reference-bound tests.
- [x] Record validation evidence and commit before Task 2.

### Task 2: Main environment Paddle Providers

**Files:**
- Modify: `.venv/` (Git-ignored environment)
- Update: `docs/PROVIDER_RUNTIME_VALIDATION.md`

**Interfaces:**
- Produces: validated `paddleocr_v5_mobile` and `paddleocr_vl_16` using existing PaddleX cache only.

- [x] Confirm required model directories already exist under `/Users/admin/.paddlex`.
- [x] Install exactly `paddleocr==3.6.0`, `paddlepaddle==3.2.1`, and `paddlex==3.6.1`.
- [x] For each Provider run import, Registry resolve, preflight, cache-only single-task execution, and canonical normalization.
- [x] If a required model is absent, record lookup evidence and stop that Provider without downloading.
- [x] Run required test suites, update the validation matrix, and commit before Task 3.

### Task 3: MinerU worker environment

**Files:**
- Create: `.venv-mineru/` (Git-ignored environment)
- Update: `docs/PROVIDER_RUNTIME_VALIDATION.md`

**Interfaces:**
- Produces: subprocess-only `mineru_local` PAGE_DOCUMENT_LAYOUT_PARSE smoke with clean worker shutdown.

- [x] Create a Python 3.12 arm64 environment and install exactly `mineru==3.4.5`.
- [x] Configure shared Hugging Face cache and local MinerU model source without copying or downloading artifacts.
- [x] Run import in worker environment, main-environment preflight, Registry resolve, one layout task, canonical normalization, and orphan-process check.
- [x] Run required test suites, update evidence, and commit before Task 4.

### Task 4: Marker worker environment

**Files:**
- Create: `.venv-marker/` (Git-ignored environment)
- Update: `docs/PROVIDER_RUNTIME_VALIDATION.md`

**Interfaces:**
- Produces: subprocess-only `marker_local` REGION and INLINE smoke results with clean shutdown.

- [x] Create Python 3.12 arm64 environment and install exactly `marker-pdf==2.0.0`.
- [x] Reuse existing Hugging Face Marker/Surya-transitive caches in offline mode.
- [x] Run import, preflight, Registry resolve, REGION and INLINE tasks, canonical normalization, and orphan-process check.
- [x] Run required test suites, update evidence, and commit before Task 5.

### Task 5: Docling worker environment

**Files:**
- Create: `.venv-docling/` (Git-ignored environment)
- Update: `docs/PROVIDER_RUNTIME_VALIDATION.md`

**Interfaces:**
- Produces: subprocess-only `docling_local` one-task smoke with clean shutdown.

- [ ] Create Python 3.12 arm64 environment and install exactly `docling==2.127.0`.
- [ ] Reuse existing Docling Hugging Face caches in offline mode.
- [ ] Run import, preflight, Registry resolve, one task, canonical normalization, and orphan-process check.
- [ ] Run required test suites, update evidence, verify Frozen SHA and clean Git state, then commit.
