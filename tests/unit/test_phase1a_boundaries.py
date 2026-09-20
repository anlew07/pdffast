from pathlib import Path

import pytest


@pytest.mark.parametrize("module_name", ["pdffast.native", "pdffast.template"])
def test_phase1a_namespaces_belong_to_v2(module_name: str) -> None:
    """Catches missing namespaces or accidental imports from the reference tree."""
    try:
        module = __import__(module_name, fromlist=["__file__"])
    except ModuleNotFoundError as exc:
        pytest.fail(f"Phase 1A namespace is missing: {exc}")

    module_file = Path(module.__file__).resolve()
    assert "pdffast-v2" in module_file.parts
