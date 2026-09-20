# PDFFast v2 Phase 1B Implementation Plan

> Execute this plan with behavior-lock TDD. The old tree remains read-only and every reference-bound test verifies the committed source manifest before comparison.

**Goal:** Migrate Stage 4 page-structure construction and Stage 5 table recovery into package APIs without changing artifacts, then prove Stage 1–5 parity on a real sample.

**Architecture:** Keep each production algorithm intact in `pdffast.native`. Replace only CLI parsing with typed callable wrappers. Stage 4 emits one JSON artifact. Stage 5 emits its existing three-file artifact directory. No cache, concurrency, threshold, ordering, or serialization changes are allowed.

**Dependencies:** Existing Python 3.12 standard library and the already-approved `pdfplumber` dependency used by Stage 1. No new dependency or provider environment is required.

---

## Task 1: Freeze Phase 1B interfaces and characterization inputs

**Files:**
- Create: `tests/regression/test_page_structure_parity.py`
- Reference: `scripts/4_page_structure_builder.py`

**Interface:**

```python
def run_page_structure(
    *,
    snapshot_path: Path,
    profile_path: Path,
    alignment_path: Path,
    output_path: Path,
) -> dict[str, Any]: ...
```

- Build shared Stage 1–3 inputs through public v2 APIs.
- Run the old Stage 4 CLI with explicit paths.
- Run RED; failure must be the absent `pdffast.native.structure` module/API.
- Compare `page_structure.json` byte-for-byte.

## Task 2: Migrate Stage 4 Page Structure

**Files:**
- Create: `pdffast/native/structure.py`
- Modify: `tests/regression/test_page_structure_parity.py`

- Preserve reference source hash `6f7b8634e4882d13cfba1ce3ccd27705336314ff39104625d6992f1c0129fffd`.
- Transplant the algorithm without changing validation, block construction, ordering, geometry, complexity priors, cross-page candidates, or constants.
- Add only the package wrapper and identical `ensure_ascii=False, indent=2` serialization without trailing newline.
- Run focused real-sample parity and the default suite.
- Commit.

## Task 3: Characterize and migrate Stage 5 Table Recovery

**Files:**
- Create: `tests/regression/test_table_recovery_parity.py`
- Create: `pdffast/native/tables.py`

**Interface:**

```python
def run_table_recovery(
    *,
    structure_path: Path,
    snapshot_path: Path,
    output_dir: Path,
) -> dict[str, Any]: ...
```

- Preserve reference source hash `53579bafcc32da89b5e52b40859285dbbf69fcc8b7a6678ff8b84de67d899957`.
- Build shared Stage 1–4 inputs through public v2 APIs.
- Run the old Stage 5 CLI and capture `result.json`, `result.md`, and `logical_tables.md`.
- Run RED; failure must be the absent `pdffast.native.tables` module/API.
- Transplant the algorithm without changing overflow recovery, table grouping, row/cell provenance, cross-page logic, rendering, ordering, or constants.
- Add only the package wrapper and reproduce the JSON trailing newline plus both Markdown renderers exactly.
- Compare all three artifacts byte-for-byte; run the default suite.
- Commit.

## Task 4: Add Stage 1–5 integrated parity

**Files:**
- Create: `tests/regression/test_phase1b_pipeline_parity.py`

- Run old Stages 1–5 sequentially with explicit paths.
- Capture all eight artifacts: four Phase 1A artifacts, Stage 4 JSON, and three Stage 5 files.
- Run new public APIs over the same paths so absolute-path provenance remains comparable.
- Report the first byte drift by artifact name.
- Require all eight artifacts to be byte-identical on `case_002.pdf`.

## Task 5: Verify and document Phase 1B

**Files:**
- Modify: `README.md`
- Modify: `docs/MIGRATION_PLAN.md`

- Run the complete default suite without external variables; external parity tests must SKIP explicitly.
- Run the complete suite with `PDFFAST_REFERENCE_ROOT` and `PDFFAST_SAMPLE_PDF` set.
- Verify the old source manifest and frozen configurations.
- Run `git diff --check` and confirm a clean worktree after commit.
- Record Phase 1B complete and leave Stage 6 / Phase 1C in progress.
