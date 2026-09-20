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

