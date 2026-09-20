from pathlib import Path

import pytest


def test_package_is_loaded_from_v2_tree() -> None:
    """Catches importing the reference package or omitting v2 package metadata."""
    try:
        import pdffast
    except ModuleNotFoundError as exc:
        pytest.fail(f"pdffast package is not importable: {exc}")

    package_file = Path(pdffast.__file__).resolve()
    assert package_file.parts[-2:] == ("pdffast", "__init__.py")
    assert "pdffast-v2" in package_file.parts
    assert pdffast.__version__ == "0.1.0"
