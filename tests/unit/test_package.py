from pathlib import Path
import re

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


def test_public_parser_api_is_importable_from_package_root() -> None:
    """Catches dropping the stable tool-facing imports during refactoring."""
    from pdffast import PDFFastParser, ParseResult, ParserConfig

    assert PDFFastParser.__name__ == "PDFFastParser"
    assert ParserConfig.__name__ == "ParserConfig"
    assert ParseResult.__name__ == "ParseResult"


def test_readme_python_examples_compile() -> None:
    """Catches publishing malformed or mislabeled Python quick-start examples."""
    readme = Path(__file__).resolve().parents[2] / "README.md"
    examples = re.findall(r"```python\n(.*?)```", readme.read_text(encoding="utf-8"), re.DOTALL)

    assert examples, "README 必须至少包含一个 Python 示例"
    for index, example in enumerate(examples, start=1):
        compile(example, f"README.md:python-example-{index}", "exec")
