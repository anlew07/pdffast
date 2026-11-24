# Real-data regression tests

These tests exercise current V3 behavior against real PDFs or previously generated regression
artifacts. They are excluded from the default deterministic suite so a fresh checkout does not
silently depend on untracked data under `outputs/`.

For PDF-backed cases, set `PDFFAST_TEST_DATA_ROOT` to a directory containing
`benchmark/samples/real/case_003.pdf` and related samples.

For artifact-backed checks, set `PDFFAST_REGRESSION_ARTIFACTS_ROOT` to a directory containing
`final_structure_regression/case_002`, `case_003`, `case_004` and/or
`template_removal_review/case_003`, `case_004`.

Run explicitly:

```bash
PDFFAST_TEST_DATA_ROOT=/path/to/test-data \
PDFFAST_REGRESSION_ARTIFACTS_ROOT=/path/to/regression-outputs \
  uv run pytest -q -m regression
```

Missing data is reported as a clear skip. A skipped regression is not an acceptance result.
