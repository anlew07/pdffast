# PDFFast v2

PDFFast v2 is a clean, behavior-preserving migration of the validated
PDFFast PDF-to-Markdown pipeline.

The project is currently in **Phase 0**. This phase contains migration and
regression infrastructure only; the production parser has not yet been
migrated. See [`docs/MIGRATION_PLAN.md`](docs/MIGRATION_PLAN.md) for the
approved architecture, boundaries, and acceptance criteria.

The future production entry point will be:

```bash
uv run python scripts/run_pipeline.py <PDF>
```

That command is intentionally not implemented in Phase 0. No PDF samples,
model files, provider environments, or generated outputs are included in the
repository.

## Phase 0 tests

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

