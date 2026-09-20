# PDFFast v2

PDFFast v2 is a clean, behavior-preserving migration of the validated
PDFFast PDF-to-Markdown pipeline.

The project is currently in **Phase 1**. Phase 0 migration infrastructure is
complete, and Phase 1A has migrated the behavior-locked Stage 1–3 native path:
page profiling, template detection, and section alignment. See
[`docs/MIGRATION_PLAN.md`](docs/MIGRATION_PLAN.md) for the approved
architecture, boundaries, and acceptance criteria.

The future production entry point will be:

```bash
uv run python scripts/run_pipeline.py <PDF>
```

That command remains intentionally unavailable until the complete production
path is migrated. No PDF samples, model files, provider environments, or
generated outputs are included in the repository.

## Tests

Run the dependency-free migration contracts and synthetic regression fixtures:

```bash
uv run pytest tests/unit tests/contracts tests/regression -v
```

Verify that the local reference implementation still matches the committed
source baseline:

```bash
PDFFAST_REFERENCE_ROOT=/Users/admin/Workspace/pdffast \
  uv run pytest tests/contracts/test_source_baseline.py -v
```

Tests marked `integration`, `regression`, or `provider` may require an
explicitly supplied PDF or optional Provider environment in later phases.
Missing external prerequisites are reported as `SKIP`; a skipped external
test is never presented as a successful provider or end-to-end run.

The committed fixtures in `tests/fixtures/artifacts/` are synthetic and do not
contain content from the real benchmark PDFs.

Run the Phase 1A Stage 1–3 parity test against an explicit local reference and
sample PDF:

```bash
PDFFAST_REFERENCE_ROOT=/Users/admin/Workspace/pdffast \
PDFFAST_SAMPLE_PDF=/absolute/path/to/sample.pdf \
  uv run pytest tests/regression/test_phase1a_pipeline_parity.py -v
```

The test runs both implementations and requires byte-identical
`page_profile.json`, `page_snapshot.jsonl`, `template_analysis.json`, and
`section_alignment.json` artifacts.
