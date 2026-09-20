# PDFFast v2 Phase 0 Baseline and Test Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create the standalone `pdffast-v2` project skeleton and a deterministic regression harness that can prove later migration slices preserve the reference implementation's artifacts.

**Architecture:** Phase 0 contains no PDF parsing algorithm. It establishes immutable artifact paths, captures reference-source checksums, copies and verifies frozen production configuration, normalizes only approved runtime metadata for JSON comparison, compares final Markdown byte-for-byte, and prepares opt-in reference-run commands without requiring real PDFs or heavy providers in the default test suite.

**Tech Stack:** Python 3.12, `uv`, standard library (`dataclasses`, `hashlib`, `json`, `pathlib`, `subprocess`), `pytest` as a development dependency.

## Global Constraints

- The reference project `/Users/admin/Workspace/pdffast` is read-only and must not be modified.
- The new project is `/Users/admin/Workspace/pdffast-v2` and must not depend on reference source code at runtime.
- Do not copy real PDFs or add them to Git.
- Do not install dependencies, download models, use API keys, or incur external costs without one consolidated user approval.
- Do not change algorithm thresholds, Quality Gate behavior, provider order, runtime escalation, Markdown semantics, or artifact semantics.
- The frozen route configuration must remain byte-for-byte identical with SHA-256 `0d999777e130de54ff25248c02cf39ae37e9fe7c5ef9231650aa3304008772d3`.
- `llm_ready.md` comparison is byte-for-byte; JSON normalization may ignore only the explicit metadata allowlist.
- Ground Truth, quality evaluator outputs, holdout labels, and DEV correctness labels must never enter production runtime.
- Phase 0 adds no migrated parser implementation and runs without heavy Provider environments.

---

## Planned File Structure

```text
pdffast-v2/
├── pyproject.toml
├── README.md
├── .gitignore
├── pdffast/
│   ├── __init__.py
│   └── pipeline/
│       ├── __init__.py
│       ├── artifacts.py
│       └── context.py
├── configs/
│   ├── templates.json
│   ├── providers.json
│   └── frozen/
│       └── stage9_route_candidates_prod_v001.json
├── tools/
│   └── migration/
│       ├── __init__.py
│       ├── baseline.py
│       ├── compare_artifacts.py
│       └── run_reference.py
├── tests/
│   ├── conftest.py
│   ├── fixtures/
│   │   └── artifacts/
│   ├── unit/
│   │   ├── test_artifact_paths.py
│   │   └── test_pipeline_context.py
│   ├── contracts/
│   │   ├── test_frozen_configs.py
│   │   └── test_source_baseline.py
│   └── regression/
│       ├── test_compare_artifacts.py
│       └── test_reference_command.py
└── docs/
    ├── MIGRATION_PLAN.md
    └── superpowers/plans/2026-09-20-pdffast-v2-phase-0.md
```

`outputs/` and `benchmark/samples/` are runtime directories created locally when needed and remain ignored by Git.

### Task 1: Standalone project packaging and test bootstrap

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `README.md`
- Create: `pdffast/__init__.py`
- Create: `pdffast/pipeline/__init__.py`
- Create: `tests/conftest.py`
- Test: `tests/unit/test_package.py`

**Interfaces:**
- Consumes: Python 3.12 and `uv`; no reference-project imports.
- Produces: importable package `pdffast`, constant `pdffast.__version__: str`, and pytest markers `integration`, `regression`, `provider`.

- [ ] **Step 1: Write the failing package test**

```python
from pathlib import Path

import pdffast


def test_package_is_loaded_from_v2_tree() -> None:
    package_file = Path(pdffast.__file__).resolve()
    assert package_file.parts[-2:] == ("pdffast", "__init__.py")
    assert "pdffast-v2" in package_file.parts
    assert pdffast.__version__ == "0.1.0"
```

- [ ] **Step 2: Run the test and verify the package is absent**

Run: `uv run --with pytest pytest tests/unit/test_package.py -v`

Expected: FAIL because `pdffast` is not importable or `__version__` is absent.

- [ ] **Step 3: Add minimal packaging metadata**

Create `pyproject.toml` with:

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "pdffast"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = []

[project.optional-dependencies]
dev = ["pytest>=8.0"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-ra"
markers = [
  "integration: multi-component tests without external provider cost",
  "regression: old-vs-new artifact comparison requiring local samples",
  "provider: tests requiring an optional provider environment",
]
```

Create `pdffast/__init__.py` with `__version__ = "0.1.0"`. Keep `pdffast/pipeline/__init__.py` empty.

- [ ] **Step 4: Add repository ignore rules**

`.gitignore` must include:

```gitignore
.DS_Store
.idea/
.pytest_cache/
.coverage
htmlcov/
__pycache__/
*.py[cod]
.venv/
.venv-*/
outputs/
benchmark/samples/*.pdf
benchmark/samples/**/*.pdf
*.log
```

Do not ignore JSON/Markdown fixtures under `tests/fixtures/`.

- [ ] **Step 5: Add a scope-limited README**

Document that Phase 0 provides migration infrastructure only, link to `docs/MIGRATION_PLAN.md`, show the future command `uv run python scripts/run_pipeline.py <PDF>` as not yet implemented, and state that no PDF is included.

- [ ] **Step 6: Run the package test**

Run: `uv run --with pytest pytest tests/unit/test_package.py -v`

Expected: PASS.

- [ ] **Step 7: Initialize Git and commit the bootstrap**

Run only if `/Users/admin/Workspace/pdffast-v2/.git` does not exist:

```bash
git init
git add pyproject.toml .gitignore README.md pdffast tests/unit/test_package.py tests/conftest.py docs/MIGRATION_PLAN.md docs/superpowers/plans/2026-09-20-pdffast-v2-phase-0.md
git commit -m "chore: initialize pdffast v2 migration project"
```

Expected: one root commit; no PDF, output, model, virtualenv, or reference-project file is staged.

### Task 2: Immutable ArtifactPaths contract

**Files:**
- Create: `pdffast/pipeline/artifacts.py`
- Test: `tests/unit/test_artifact_paths.py`

**Interfaces:**
- Consumes: `run_dir: pathlib.Path`.
- Produces: frozen dataclass `ArtifactPaths` and `ArtifactPaths.for_run(run_dir: Path) -> ArtifactPaths`.
- Later tasks rely on exact property names from `docs/MIGRATION_PLAN.md` section 8.

- [ ] **Step 1: Write the failing path-map test**

```python
from pathlib import Path

from pdffast.pipeline.artifacts import ArtifactPaths


def test_artifact_paths_match_reference_layout(tmp_path: Path) -> None:
    run_dir = tmp_path / "outputs" / "case_007_20260920_120000"
    paths = ArtifactPaths.for_run(run_dir)

    expected = {
        "profile": run_dir / "01_stage1/page_profile.json",
        "snapshot": run_dir / "01_stage1/page_snapshot.jsonl",
        "template_analysis": run_dir / "02_stage2/template_analysis.json",
        "section_alignment": run_dir / "03_stage3/section_alignment.json",
        "page_structure": run_dir / "04_stage4/page_structure.json",
        "table_result": run_dir / "05_stage5/result.json",
        "normalized_flow": run_dir / "06_stage6/normalized_text_flow.json",
        "evidence_manifest": run_dir / "07_stage7/evidence_manifest.json",
        "quality_gate": run_dir / "08_stage8/quality_gate.json",
        "fallback_manifest": run_dir / "09_1_fallback_units/fallback_execution_manifest.json",
        "provider_plan": run_dir / "09_2_provider_plan/provider_plan.json",
        "runtime_policy": run_dir / "09_6_3_runtime_policy/runtime_escalation_policy.json",
        "production_manifest": run_dir / "09_8_production_fallback/production_execution_manifest.json",
        "selected_prediction_index": run_dir / "09_8_production_fallback/selected_prediction_index.json",
        "selected_predictions_dir": run_dir / "09_8_production_fallback/selected_predictions",
        "canonical_document": run_dir / "10_1_canonical/canonical_document.json",
        "render_manifest": run_dir / "10_2_llm_ready/render_manifest.json",
        "llm_ready": run_dir / "10_2_llm_ready/llm_ready.md",
        "structure_audit": run_dir / "10_2_1_structure_audit/structure_boundary_audit.json",
        "logs_dir": run_dir / "logs",
    }
    assert paths.as_dict() == expected
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `uv run --with pytest pytest tests/unit/test_artifact_paths.py -v`

Expected: FAIL because `pdffast.pipeline.artifacts` does not exist.

- [ ] **Step 3: Implement the frozen dataclass**

Implement all fields shown above, validate that `run_dir` is not the filesystem root, and make `as_dict()` return a new `dict[str, Path]` in field order.

Do not create directories inside `for_run`; path calculation must be side-effect free.

- [ ] **Step 4: Add safety and immutability tests**

```python
import dataclasses
from pathlib import Path

import pytest

from pdffast.pipeline.artifacts import ArtifactPaths


def test_artifact_paths_are_frozen(tmp_path: Path) -> None:
    paths = ArtifactPaths.for_run(tmp_path / "run")
    with pytest.raises(dataclasses.FrozenInstanceError):
        paths.profile = tmp_path / "other.json"  # type: ignore[misc]


def test_filesystem_root_is_rejected() -> None:
    with pytest.raises(ValueError, match="run_dir"):
        ArtifactPaths.for_run(Path("/"))
```

- [ ] **Step 5: Run focused tests**

Run: `uv run --with pytest pytest tests/unit/test_artifact_paths.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add pdffast/pipeline/artifacts.py tests/unit/test_artifact_paths.py
git commit -m "feat: define immutable pipeline artifact paths"
```

### Task 3: Minimal PipelineContext without service-locator behavior

**Files:**
- Create: `pdffast/pipeline/context.py`
- Test: `tests/unit/test_pipeline_context.py`

**Interfaces:**
- Consumes: project/input/output/config paths and deterministic run identity.
- Produces: frozen `PipelineContext` with `artifacts: ArtifactPaths` and `PipelineContext.create(...)`.
- Does not contain Provider objects, parsed JSON data, policies, or mutable caches.

- [ ] **Step 1: Write the failing deterministic-context test**

```python
from pathlib import Path

from pdffast.pipeline.context import PipelineContext


def test_context_resolves_paths_and_sanitizes_case_id(tmp_path: Path) -> None:
    project = tmp_path / "pdffast-v2"
    pdf = project / "benchmark/samples/科研 case 007.pdf"
    ctx = PipelineContext.create(
        project_root=project,
        pdf=pdf,
        output_root=project / "outputs",
        run_id="case_007_fixed",
        case_id=None,
        page_dpi=150,
        region_dpi=150,
        rapidocr_workers=1,
        table_mode="auto",
    )

    assert ctx.case_id == "_case_007"
    assert ctx.run_dir == project / "outputs/case_007_fixed"
    assert ctx.templates == project / "configs/templates.json"
    assert ctx.providers == project / "configs/providers.json"
    assert ctx.route_candidates == project / "configs/frozen/stage9_route_candidates_prod_v001.json"
    assert ctx.artifacts.llm_ready == ctx.run_dir / "10_2_llm_ready/llm_ready.md"
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `uv run --with pytest pytest tests/unit/test_pipeline_context.py -v`

Expected: FAIL because `PipelineContext` does not exist.

- [ ] **Step 3: Implement context creation**

Use the reference sanitization expression `re.sub(r"[^A-Za-z0-9_.-]+", "_", raw_case_id)`. Resolve paths without requiring files to exist. Validate `page_dpi > 0`, `region_dpi > 0`, `rapidocr_workers >= 1`, and `table_mode in {"off", "auto", "all"}`.

- [ ] **Step 4: Add validation tests**

Parameterize invalid DPI, workers, and table mode. Assert exact `ValueError` field names so later CLI code can report actionable errors.

- [ ] **Step 5: Run focused tests**

Run: `uv run --with pytest pytest tests/unit/test_pipeline_context.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add pdffast/pipeline/context.py tests/unit/test_pipeline_context.py
git commit -m "feat: add deterministic pipeline context"
```

### Task 4: Capture and verify the reference source baseline

**Files:**
- Create: `tools/__init__.py`
- Create: `tools/migration/__init__.py`
- Create: `tools/migration/baseline.py`
- Create: `tests/contracts/reference_source_manifest.json`
- Test: `tests/contracts/test_source_baseline.py`

**Interfaces:**
- Consumes: explicit `reference_root: Path` and a fixed relative-file allowlist.
- Produces: `capture_manifest(reference_root: Path) -> dict[str, object]` and a committed manifest with SHA-256 and size for the 18 production scripts and 3 production configs.
- Never scans `outputs/`, virtualenvs, PDFs, GT, or holdout files.

- [ ] **Step 1: Write the failing baseline test**

```python
import json
import os
from pathlib import Path

import pytest

from tools.migration.baseline import capture_manifest


def test_reference_source_matches_committed_manifest() -> None:
    raw_root = os.environ.get("PDFFAST_REFERENCE_ROOT")
    if not raw_root:
        pytest.skip("PDFFAST_REFERENCE_ROOT is not set")

    expected = json.loads(
        Path("tests/contracts/reference_source_manifest.json").read_text(encoding="utf-8")
    )
    actual = capture_manifest(Path(raw_root))
    assert actual == expected
```

- [ ] **Step 2: Run the test with the reference root and verify it fails**

Run:

```bash
PDFFAST_REFERENCE_ROOT=/Users/admin/Workspace/pdffast \
uv run --with pytest pytest tests/contracts/test_source_baseline.py -v
```

Expected: FAIL because the capture module or committed manifest is absent.

- [ ] **Step 3: Implement an explicit allowlist**

The allowlist must contain exactly the production files listed in `docs/MIGRATION_PLAN.md` section 4. For each file emit:

```json
{
  "path": "scripts/1_page_profiler.py",
  "sha256": "<64 lowercase hex chars>",
  "size_bytes": 123
}
```

Sort entries by relative path. Include manifest schema `1.0`, reference role `pdffast_reference_production_sources`, and no absolute path or timestamp.

- [ ] **Step 4: Generate the committed manifest once**

Run:

```bash
uv run python -m tools.migration.baseline \
  --reference-root /Users/admin/Workspace/pdffast \
  --output tests/contracts/reference_source_manifest.json
```

The writer must refuse to overwrite an existing file unless `--check` is used; Phase 0 must not provide a silent baseline-update option.

- [ ] **Step 5: Run baseline checks**

Run the focused test both without and with `PDFFAST_REFERENCE_ROOT`.

Expected: SKIP without the variable; PASS with the audited reference root.

- [ ] **Step 6: Commit**

```bash
git add tools tests/contracts/reference_source_manifest.json tests/contracts/test_source_baseline.py
git commit -m "test: freeze reference production source baseline"
```

### Task 5: Copy and lock production configuration

**Files:**
- Create: `configs/templates.json`
- Create: `configs/providers.json`
- Create: `configs/frozen/stage9_route_candidates_prod_v001.json`
- Test: `tests/contracts/test_frozen_configs.py`

**Interfaces:**
- Consumes: the three audited reference configuration files.
- Produces: independent v2 configuration with pinned SHA-256 assertions.

- [ ] **Step 1: Write failing checksum tests**

```python
from hashlib import sha256
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("configs/templates.json", "a3c50aafa43c2afece508b27ff9204b47bdf6a0d145547beb22fb3fd4fb546b1"),
        ("configs/providers.json", "2c8aca69d5d3f564d8282b64cc6513e008d829f3debd660afb1ef6361936f79a"),
        ("configs/frozen/stage9_route_candidates_prod_v001.json", "0d999777e130de54ff25248c02cf39ae37e9fe7c5ef9231650aa3304008772d3"),
    ],
)
def test_production_config_checksum(path: str, expected: str) -> None:
    assert sha256(Path(path).read_bytes()).hexdigest() == expected
```

- [ ] **Step 2: Run the test and verify missing-file failures**

Run: `uv run --with pytest pytest tests/contracts/test_frozen_configs.py -v`

Expected: three FAIL results because configs are absent.

- [ ] **Step 3: Copy frozen files and derive the approved Provider subset**

Copy bytes from:

```text
/Users/admin/Workspace/pdffast/configs/templates.json
/Users/admin/Workspace/pdffast/configs/stage9_providers_v011.json
/Users/admin/Workspace/pdffast/configs/frozen/stage9_route_candidates_prod_v001.json
```

Copy `templates.json` and the frozen route candidates byte-for-byte. Create `providers.json` by removing exactly these three mappings from the old provider registry and preserving all retained Provider objects unchanged:

```text
tesseract_chi_sim
surya_local
generic_cli_example
```

Serialize with UTF-8, two-space indentation, insertion order preserved, and a trailing newline. The expected target checksum is `2c8aca69d5d3f564d8282b64cc6513e008d829f3debd660afb1ef6361936f79a`.

- [ ] **Step 4: Assert the Provider migration boundary**

Add a test that parses `configs/providers.json` and asserts its provider-name set is exactly:

```python
{
    "paddleocr_v5_mobile",
    "pp_structure_v3_light",
    "paddleocr_vl_16",
    "rapidocr_ch_light",
    "docling_local",
    "mineru_local",
    "marker_local",
}
```

Also load the old registry when `PDFFAST_REFERENCE_ROOT` is set and assert each retained Provider object is deeply equal. This enforces the approved adapter boundary without changing retained runtime configuration.

- [ ] **Step 5: Run focused tests**

Run: `uv run --with pytest pytest tests/contracts/test_frozen_configs.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add configs tests/contracts/test_frozen_configs.py
git commit -m "test: lock production configuration checksums"
```

### Task 6: Deterministic JSON and Markdown artifact comparator

**Files:**
- Create: `tools/migration/compare_artifacts.py`
- Create: `tests/fixtures/artifacts/reference.json`
- Create: `tests/fixtures/artifacts/candidate_runtime_only.json`
- Create: `tests/fixtures/artifacts/candidate_semantic_change.json`
- Create: `tests/fixtures/artifacts/reference.md`
- Create: `tests/fixtures/artifacts/candidate.md`
- Test: `tests/regression/test_compare_artifacts.py`

**Interfaces:**
- Produces:
  - `normalize_json(value: object, roots: RootMapping) -> object`
  - `compare_json(reference: Path, candidate: Path, roots: RootMapping) -> ComparisonResult`
  - `compare_bytes(reference: Path, candidate: Path) -> ComparisonResult`
  - CLI exit code `0` for equal and `1` for different.
- `RootMapping` contains explicit reference and candidate project/run roots; it does not do unrestricted string replacement.

- [ ] **Step 1: Write failing normalization tests**

Tests must prove that timestamp, run ID, wall/elapsed time, PID, approved absolute root prefixes, temporary directory, and non-semantic log path are normalized while these remain significant:

```text
text, bbox, list order, route, decision, gate_state,
provider_chain, selected_provider, warnings, terminal semantics, provenance links
```

Include an assertion that `candidate_runtime_only.json` compares equal and `candidate_semantic_change.json` reports the first differing JSON Pointer plus a unified diff.

- [ ] **Step 2: Write failing Markdown byte tests**

```python
from pathlib import Path

from tools.migration.compare_artifacts import compare_bytes


def test_markdown_requires_byte_equality() -> None:
    result = compare_bytes(
        Path("tests/fixtures/artifacts/reference.md"),
        Path("tests/fixtures/artifacts/candidate.md"),
    )
    assert result.equal is False
    assert "newline" in result.summary.lower() or result.diff
```

The fixtures must differ only by a trailing newline or one space to prove Markdown is not normalized.

- [ ] **Step 3: Run tests and verify they fail**

Run: `uv run --with pytest pytest tests/regression/test_compare_artifacts.py -v`

Expected: FAIL because the comparator does not exist.

- [ ] **Step 4: Implement explicit normalization**

Use an exact-key allowlist and JSON Pointer-aware traversal. Never remove a field based on substring matching. Normalize path prefixes only for fields whose key is in the approved path-key allowlist. Preserve list order.

`ComparisonResult` is a frozen dataclass:

```python
@dataclass(frozen=True)
class ComparisonResult:
    equal: bool
    summary: str
    diff: str
```

- [ ] **Step 5: Implement CLI behavior**

Support:

```bash
uv run python -m tools.migration.compare_artifacts \
  --kind json \
  --reference <old.json> \
  --candidate <new.json> \
  --reference-root /Users/admin/Workspace/pdffast \
  --candidate-root /Users/admin/Workspace/pdffast-v2
```

and `--kind bytes` for Markdown. Print the summary/diff to stdout; never mutate inputs.

- [ ] **Step 6: Run focused tests**

Run: `uv run --with pytest pytest tests/regression/test_compare_artifacts.py -v`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add tools/migration/compare_artifacts.py tests/fixtures/artifacts tests/regression/test_compare_artifacts.py
git commit -m "test: add deterministic artifact comparison harness"
```

### Task 7: Reference-run command planner with no implicit execution

**Files:**
- Create: `tools/migration/run_reference.py`
- Test: `tests/regression/test_reference_command.py`

**Interfaces:**
- Consumes: explicit roots, PDF path, run ID, and production parameters.
- Produces: `build_reference_command(...) -> list[str]` and `build_candidate_command(...) -> list[str]`.
- Phase 0 CLI prints commands by default; `--execute` is explicit and refuses a missing PDF or pre-existing run directory.

- [ ] **Step 1: Write the failing command test**

```python
from pathlib import Path

from tools.migration.run_reference import build_reference_command


def test_reference_command_pins_all_behavior_relevant_arguments() -> None:
    cmd = build_reference_command(
        python=Path("/reference/.venv/bin/python"),
        reference_root=Path("/reference"),
        pdf=Path("/samples/case_007.pdf"),
        output_root=Path("/runs/reference"),
        run_id="case_007_parity_v001",
        page_dpi=150,
        region_dpi=150,
        rapidocr_workers=1,
        table_mode="auto",
    )
    assert cmd == [
        "/reference/.venv/bin/python",
        "/reference/scripts/pipeline_observed_runner.py",
        "/samples/case_007.pdf",
        "--output-root", "/runs/reference",
        "--run-id", "case_007_parity_v001",
        "--page-dpi", "150",
        "--region-dpi", "150",
        "--rapidocr-workers", "1",
        "--table-mode", "auto",
        "--route-candidates", "/reference/configs/frozen/stage9_route_candidates_prod_v001.json",
        "--provider-config", "/reference/configs/stage9_providers_v011.json",
        "--templates", "/reference/configs/templates.json",
    ]
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `uv run --with pytest pytest tests/regression/test_reference_command.py -v`

Expected: FAIL because the command planner is absent.

- [ ] **Step 3: Implement pure command builders**

Use list arguments only; never construct shell strings. Keep all behavior-relevant defaults explicit so old and new runs cannot silently diverge.

Until the v2 runner exists, `build_candidate_command` raises `NotImplementedError("candidate pipeline is introduced in Phase 4")`; test that exact behavior.

- [ ] **Step 4: Implement safe CLI planning**

Default behavior prints JSON arrays for both commands and exits without running them. `--execute reference` may run only the reference command after validating the PDF exists and target run directory does not exist. Do not add overwrite or cleanup flags.

- [ ] **Step 5: Run focused tests**

Run: `uv run --with pytest pytest tests/regression/test_reference_command.py -v`

Expected: PASS without invoking the old Pipeline.

- [ ] **Step 6: Commit**

```bash
git add tools/migration/run_reference.py tests/regression/test_reference_command.py
git commit -m "test: add explicit reference run planner"
```

### Task 8: Phase 0 verification and documentation handoff

**Files:**
- Modify: `README.md`
- Create: `tests/fixtures/artifacts/README.md`
- Modify: `docs/MIGRATION_PLAN.md`

**Interfaces:**
- Consumes: Tasks 1–7.
- Produces: a documented, passing Phase 0 baseline with no parser algorithm code.

- [ ] **Step 1: Document the test tiers**

README must provide exact commands:

```bash
uv run --with pytest pytest tests/unit tests/contracts tests/regression -v
PDFFAST_REFERENCE_ROOT=/Users/admin/Workspace/pdffast \
  uv run --with pytest pytest tests/contracts/test_source_baseline.py -v
```

Explain that `integration`, `regression`, and `provider` tests requiring samples/environments are opt-in and why missing prerequisites cause SKIP rather than PASS.

- [ ] **Step 2: Document fixture provenance**

`tests/fixtures/artifacts/README.md` must state for every fixture whether it is synthetic or copied from a reference artifact, the source artifact schema/version, and whether it contains sensitive PDF content. Phase 0 fixtures should be synthetic and contain no real applicant data.

- [ ] **Step 3: Mark Phase 0 status in the migration plan**

Add a short status table to `docs/MIGRATION_PLAN.md` with Phase 0 marked complete only after all verification commands pass; Phases 1–5 remain planned. Do not alter the design requirements.

- [ ] **Step 4: Run the complete default suite**

Run: `uv run --with pytest pytest -v`

Expected: all default tests PASS; environment-dependent tests SKIP with explicit reasons; no test invokes a heavy Provider or opens a real PDF.

- [ ] **Step 5: Verify repository hygiene**

Run:

```bash
git status --short
git ls-files | rg '(\.pdf$|^outputs/|\.venv|__pycache__|\.pyc$)'
```

Expected: the second command prints nothing. Review `git diff --check`; expected exit code `0`.

- [ ] **Step 6: Commit the Phase 0 handoff**

```bash
git add README.md docs/MIGRATION_PLAN.md tests/fixtures/artifacts/README.md
git commit -m "docs: complete phase zero migration baseline"
```

- [ ] **Step 7: Record verification evidence**

Capture in the final handoff:

- exact pytest command and pass/skip counts;
- frozen config checksums;
- reference baseline check result;
- confirmation that `/Users/admin/Workspace/pdffast` has not been modified;
- list of intentionally deferred Phase 1 work.

Do not claim Phase 0 complete without fresh command output from Steps 4–5.
