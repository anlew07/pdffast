# PDFFast v2 Phase 2 Implementation Plan

**Goal:** Migrate Stage 7, Stage 8, Stage 9.1, Stage 9.2, and Stage 9.6.3 while preserving quality decisions, fallback task identity, routing, frozen provider chains, and artifact bytes.

**Architecture:** Use four package areas: `quality.evidence`, `quality.gate`, `fallback.planner`, and `fallback.policy`. Stage 9.1 and 9.2 remain separate public calls inside `planner.py` only if their source algorithms stay visibly sealed. Stage 9.6.3 consumes the frozen route-candidate config copied in Phase 0. No provider is invoked in Phase 2.

**Dependencies:** Existing `pdfplumber` and Pillow are sufficient for Stage 8 probes and Stage 9.1 rendering. No new dependency, model, key, or external cost is required.

## Task 1: Stage 7 evidence manifest

- Add a real-sample parity test for `evidence_manifest.json` and `.md`.
- Migrate source hash from the committed reference manifest into `pdffast.quality.evidence`.
- Add `run_evidence_manifest(...)`; preserve JSON trailing newline and Markdown exactly.
- Run focused and default suites; commit.

## Task 2: Stage 8 quality gate

- Add parity for `quality_gate.json`, `.md`, and every saved probe crop path/byte.
- Migrate to `pdffast.quality.gate` with `run_quality_gate(...)`.
- Preserve probe DPI, hard routes, uncertainty logic, crop rendering, and serialization.
- Run focused and default suites; commit.

## Task 3: Stage 9.1 fallback unit planning

- Add parity for manifest JSON/Markdown and every rendered task input PNG.
- Migrate to `pdffast.fallback.planner.run_fallback_planning(...)`.
- Preserve task IDs, bboxes, input paths, DPI, ordering, and route hints.
- Run focused and default suites; commit.

## Task 4: Stage 9.2 capability routing

- Add parity for `provider_plan.json` and `.md`.
- Migrate capability routing without binding providers or invoking external tools.
- Preserve task order and output contracts; commit after focused/default tests.

## Task 5: Stage 9.6.3 runtime escalation policy

- Add parity against `configs/frozen/stage9_route_candidates_prod_v001.json`.
- Migrate to `pdffast.fallback.policy.run_runtime_policy(...)`.
- Preserve provider chains, acceptance rules, terminal fallback, and provisional status.
- Assert production modules do not import GT, evaluator, holdout, or benchmark selection logic.

## Task 6: Phase 2 integration and verification

- Run reference and candidate Stage 1–9.6.3 over identical paths.
- Compare Phase 2 JSON/Markdown plus rendered crop/task-input bytes.
- Run the default and reference-bound complete suites, source baseline, frozen configs, and `git diff --check`.
- Update README and `docs/MIGRATION_PLAN.md`; mark Phase 2 complete only after all comparisons pass.
