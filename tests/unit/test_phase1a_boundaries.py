from pathlib import Path
import os

import pytest


@pytest.mark.parametrize("module_name", ["pdffast.native", "pdffast.template"])
def test_phase1a_namespaces_belong_to_current_repository(module_name: str) -> None:
    """Catches missing namespaces or accidental imports from the reference tree."""
    try:
        module = __import__(module_name, fromlist=["__file__"])
    except ModuleNotFoundError as exc:
        pytest.fail(f"Phase 1A namespace is missing: {exc}")

    module_file = Path(module.__file__).resolve()
    repo_root = Path(__file__).resolve().parents[2]
    assert module_file == repo_root / Path(*module_name.split(".")) / "__init__.py"
    reference_root = os.environ.get("PDFFAST_REFERENCE_ROOT")
    if reference_root and Path(reference_root).resolve() != repo_root:
        assert not module_file.is_relative_to(Path(reference_root).resolve())
