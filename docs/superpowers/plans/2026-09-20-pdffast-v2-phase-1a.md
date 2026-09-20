# PDFFast v2 Phase 1A Native Intake and Template Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate the current production behavior of Stage 1 Page Profiler, Stage 2 Template Analyzer, and Stage 3 Section Aligner into responsibility-named v2 modules with byte-identical artifacts.

**Architecture:** Preserve audited algorithm constants and function bodies while replacing stage-script CLI ownership with explicit `run_*` APIs. Regression tests execute the reference scripts and v2 modules against the same externally located PDF, then compare all four artifacts byte-for-byte. Shared-helper extraction is deferred until parity is proven so DRY work cannot obscure migration defects.

**Tech Stack:** Python 3.12, `pdfplumber>=0.11.10`, standard library, pytest, existing Phase 0 ArtifactPaths and source-baseline tools.

## Global Constraints

- `/Users/admin/Workspace/pdffast` remains read-only.
- No real PDF is copied into v2 or committed.
- No algorithm threshold, branch order, artifact field, JSON formatting, template semantics, or heading heuristic changes.
- No Ground Truth, benchmark ranking, holdout, or provider code enters these modules.
- The reference source manifest must pass before each parity run.
- New modules expose APIs; the final public CLI remains deferred until Phase 4.
- Do not extract same-named helpers to `core/` until byte parity is green.
- Missing external sample prerequisites produce an explicit SKIP in the default suite, never a false PASS.

---

### Task 1: Native/template package boundary and dependency declaration

**Files:**
- Modify: `pyproject.toml`
- Create: `pdffast/native/__init__.py`
- Create: `pdffast/template/__init__.py`
- Test: `tests/unit/test_phase1a_boundaries.py`

**Interfaces:**
- Produces importable `pdffast.native` and `pdffast.template` namespaces.
- Declares only `pdfplumber>=0.11.10` as the first production dependency.

- [ ] Write a failing test that imports both namespaces and asserts the v2 package path.
- [ ] Run the focused test and observe failure because namespaces are absent.
- [ ] Add empty namespace modules with responsibility docstrings.
- [ ] Add `pdfplumber>=0.11.10` to `[project].dependencies` without adding Provider packages.
- [ ] Synchronize only after consolidated dependency approval.
- [ ] Run the focused test under Python 3.12 and commit.

### Task 2: Page Profiler migration

**Files:**
- Create: `pdffast/native/profiler.py`
- Create: `tests/regression/test_profiler_parity.py`

**Interfaces:**
- Preserves the audited Stage 1 algorithm from `scripts/1_page_profiler.py` at reference hash `8ac3c7810b0dcba5f7c6f149951b964d8d28500fa5c105fae905234d9977e286`.
- Produces:

```python
def run_profiler(
    *,
    pdf_path: Path,
    profile_output: Path,
    snapshot_output: Path,
    table_mode: str = "auto",
) -> dict[str, Any]: ...
```

- `run_profiler` validates PDF existence/suffix, calls the unchanged `scan_and_profile_pdf`, writes the same indented UTF-8 JSON without a trailing newline, and returns the result.

- [ ] Write a regression test gated by `PDFFAST_REFERENCE_ROOT` and `PDFFAST_SAMPLE_PDF`.
- [ ] In the test, verify the committed reference source manifest first.
- [ ] Execute the old Stage 1 script into `tmp_path/reference` with explicit `--table-mode auto`.
- [ ] Call `run_profiler` into `tmp_path/candidate`.
- [ ] Assert `page_profile.json` and `page_snapshot.jsonl` bytes are identical.
- [ ] Run the test and observe failure because `pdffast.native.profiler` is absent.
- [ ] Mechanically transplant only the production algorithm and reporting helpers; remove `argparse` ownership and `if __name__ == "__main__"`.
- [ ] Add the minimal `run_profiler` wrapper.
- [ ] Run profiler parity on `benchmark/samples/real/case_002.pdf`; expected PASS.
- [ ] Run the default suite; expected external parity test SKIP without environment variables.
- [ ] Commit.

### Task 3: Template Detector migration

**Files:**
- Create: `pdffast/template/detector.py`
- Create: `tests/regression/test_template_detector_parity.py`

**Interfaces:**
- Preserves `scripts/2_template_analyzer.py` at reference hash `0eb2fdf047de1639138ce6419c355b6c6452faac8d8128c6e705881133aeb1ab`.
- Produces:

```python
def run_template_analysis(
    *,
    profile_path: Path,
    template_path: Path,
    output_path: Path,
) -> dict[str, Any]: ...
```

- [ ] Write a parity test that first obtains one candidate/reference profile pair from the same PDF.
- [ ] Run the old Stage 2 script against the reference profile and `configs/templates.json`.
- [ ] Call `run_template_analysis` against the byte-equal candidate profile and v2 templates.
- [ ] Assert `template_analysis.json` bytes are identical.
- [ ] Run RED; expected failure because detector module/API is absent.
- [ ] Transplant the Stage 2 production algorithm without changing constants, normalization, scores, tie-breaks, or output ordering.
- [ ] Add the minimal API wrapper using `ensure_ascii=False, indent=2` and no trailing newline.
- [ ] Run parity and the default suite.
- [ ] Commit.

### Task 4: Section Aligner migration

**Files:**
- Create: `pdffast/template/aligner.py`
- Create: `tests/regression/test_section_aligner_parity.py`

**Interfaces:**
- Preserves `scripts/3_section_aligner.py` at reference hash `fd16abedb0ef69bbca40631a0259d08a76a64d82decea955be8fdf1b02ad655f`.
- Produces:

```python
def run_section_alignment(
    *,
    analysis_path: Path,
    template_path: Path,
    snapshot_path: Path | None,
    output_path: Path,
) -> dict[str, Any]: ...
```

- [ ] Write a parity test using byte-equal Stage 1 snapshot and Stage 2 analysis artifacts.
- [ ] Run the old Stage 3 script with explicit `--templates` and `--snapshot`.
- [ ] Call `run_section_alignment` with the same semantic inputs.
- [ ] Assert `section_alignment.json` bytes are identical.
- [ ] Run RED; expected failure because aligner module/API is absent.
- [ ] Transplant the Stage 3 production algorithm without changing candidate ranking, assisted mode, generic heading recovery, ranges, unresolved regions, or page map order.
- [ ] Add the minimal API wrapper with identical serialization.
- [ ] Run parity and the default suite.
- [ ] Commit.

### Task 5: Phase 1A integrated parity and documentation

**Files:**
- Create: `tests/regression/test_phase1a_pipeline_parity.py`
- Modify: `README.md`
- Modify: `docs/MIGRATION_PLAN.md`

**Interfaces:**
- Runs Stage 1–3 sequentially in reference and candidate trees using the same PDF and explicit configuration.
- Compares four artifacts byte-for-byte and reports the first differing file.

- [ ] Write the integrated test before adding any integration helper.
- [ ] Reuse public v2 APIs, not private functions or copied reference logic.
- [ ] Run with:

```bash
PDFFAST_REFERENCE_ROOT=/Users/admin/Workspace/pdffast \
PDFFAST_SAMPLE_PDF=/Users/admin/Workspace/pdffast/benchmark/samples/real/case_002.pdf \
  .venv/bin/python -m pytest -p no:cacheprovider \
  tests/regression/test_phase1a_pipeline_parity.py -v
```

- [ ] Expected: all four artifact comparisons PASS.
- [ ] Run the complete default suite; external parity tests SKIP without environment variables.
- [ ] Run the reference source-baseline check and `git diff --check`.
- [ ] Update migration status to Phase 1A complete; leave Phase 1B–1D planned.
- [ ] Commit the verified handoff.

