from pathlib import Path
import re

import pytest

from pdffast import PDFFastParser
from pdffast.errors import ConfigurationError


def test_package_is_loaded_from_current_repository() -> None:
    """Catches importing the reference package or omitting package metadata."""
    try:
        import pdffast
    except ModuleNotFoundError as exc:
        pytest.fail(f"pdffast package is not importable: {exc}")

    package_file = Path(pdffast.__file__).resolve()
    assert package_file.parts[-2:] == ("pdffast", "__init__.py")
    repo_root = Path(__file__).resolve().parents[2]
    assert package_file == repo_root / "pdffast/__init__.py"
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



@pytest.mark.parametrize(
    "run_id",
    ["../escape", "nested/run", "/tmp/escape", ".", "..", r"..\\escape", "bad\x00name"],
)
def test_parser_rejects_run_ids_that_escape_output_root(tmp_path, run_id):
    parser = PDFFastParser(output_root=tmp_path / "outputs")

    with pytest.raises(ConfigurationError, match="run_id"):
        parser.parse(tmp_path / "unused.pdf", run_id=run_id)

    assert not (tmp_path / "outputs").exists()
    assert not (tmp_path / "escape").exists()


def test_parser_rejects_symlinked_run_directory(tmp_path):
    output_root = tmp_path / "outputs"
    output_root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (output_root / "alias").symlink_to(outside, target_is_directory=True)
    parser = PDFFastParser(output_root=output_root)

    with pytest.raises(ConfigurationError, match="symlink"):
        parser.parse(tmp_path / "unused.pdf", run_id="alias")

    assert list(outside.iterdir()) == []
