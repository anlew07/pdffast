# V2 → V3 migration tests

This directory contains historical parity checks only. These tests may read a separate, read-only V2
checkout and compare its recorded artifacts with V3 behavior. They are not current V3 runtime
dependencies and are excluded from the default test suite.

Run explicitly when migration evidence is required:

```bash
PDFFAST_REFERENCE_ROOT=/path/to/read-only-v2 \
PDFFAST_SAMPLE_PDF=/path/to/case_002.pdf \
  uv run pytest -q -m migration
```

Do not point this variable at the active V3 checkout. Do not use a migration test's historical PASS
as evidence for the current V3 commit.
