# PDFFast v2 Phase 1C Implementation Plan

> Execute with behavior-lock TDD. Stage 6 is migrated as one sealed production unit before any internal decomposition.

**Goal:** Migrate Stage 6 Text Flow and prove the complete Stage 1–6 native pipeline produces byte-identical artifacts.

**Architecture:** Place the intact Stage 6 algorithm in `pdffast.native.text_flow`; replace only CLI parsing with one callable wrapper. Preserve all six internal substage boundaries and all eleven output files. No helper deduplication, caching, performance work, threshold changes, or algorithm splitting is permitted in this slice.

**Dependencies:** No new dependency. Use the existing Phase 1B package APIs and reference runner.

---

## Task 1: Characterize Stage 6 outputs

**Files:**
- Create: `tests/regression/test_text_flow_parity.py`

**Interface:**

```python
def run_text_flow(
    *,
    snapshot_path: Path,
    structure_path: Path,
    table_result_path: Path,
    output_dir: Path,
) -> dict[str, Any]: ...
```

- Build shared Stage 1–5 artifacts through public v2 APIs.
- Run the old Stage 6 CLI with explicit inputs.
- Assert RED fails only because `pdffast.native.text_flow` is absent.
- Lock all eleven artifacts byte-for-byte: five JSON files and six Markdown files.

## Task 2: Migrate Stage 6 as a sealed unit

**Files:**
- Create: `pdffast/native/text_flow.py`
- Modify: `tests/regression/test_text_flow_parity.py`

- Preserve source hash `7820c33dac710c7b8c142dba9d35f2039df64ea13797087e7e36e1624d50cbba`.
- Transplant the implementation without changing Stage 6.1–6.6 algorithms, constants, ordering, ownership, suppression, noise actions, table materialization, or renderers.
- Add only `run_text_flow`; reproduce `json.dump(..., ensure_ascii=False, indent=2)` with no trailing newline and all Markdown writers exactly.
- Run focused parity and the default suite.
- Commit.

## Task 3: Add complete Native Stage 1–6 parity

**Files:**
- Create: `tests/regression/test_phase1_native_pipeline_parity.py`

- Run old Stages 1–6 and candidate package APIs over identical paths.
- Compare the eight Phase 1B artifacts plus all eleven Stage 6 artifacts.
- Report the first byte drift by artifact name.
- Require all nineteen artifacts to match on `case_002.pdf`.

## Task 4: Verify and document Phase 1

**Files:**
- Modify: `README.md`
- Modify: `docs/MIGRATION_PLAN.md`

- Run the default suite and explicit reference-bound suite.
- Verify frozen configs, source manifest, `git diff --check`, and final clean worktree.
- Mark Phase 1 complete only if Stage 1–6 integration passes all nineteen artifact comparisons.
- Leave Phase 2 planning separate from Phase 1 implementation.
