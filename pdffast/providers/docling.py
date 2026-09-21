from __future__ import annotations

from typing import Any

from .base import ProviderTask
from .workers import IsolatedWorkerProvider


WORKER_CODE = r'''
import json, sys, time, traceback
from pathlib import Path
try:
    from docling.document_converter import DocumentConverter
    converter = DocumentConverter()
    print(json.dumps({"status": "READY", "sys_executable": sys.executable}), flush=True)
except Exception as exc:
    print(json.dumps({"status": "INIT_FAILED", "error": f"{type(exc).__name__}: {exc}"}), flush=True)
    raise
for line in sys.stdin:
    command = json.loads(line)
    if command.get("op") == "close":
        print(json.dumps({"status": "BYE"}), flush=True); break
    started = time.perf_counter()
    try:
        output = Path(command["output_dir"]); output.mkdir(parents=True, exist_ok=True)
        converted = converter.convert(command["input"])
        markdown = converted.document.export_to_markdown()
        path = output / "result.md"; path.write_text(markdown or "", encoding="utf-8")
        print(json.dumps({"status": "SUCCESS", "markdown_path": str(path), "raw_refs": [str(path)], "elapsed_seconds": time.perf_counter() - started}), flush=True)
    except Exception as exc:
        print(json.dumps({"status": "FAILED", "error": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc()}), flush=True)
'''


class DoclingProvider(IsolatedWorkerProvider):
    default_python = ".venv-docling/bin/python"
    result_path_key = "markdown_path"
    worker_code = WORKER_CODE
    dependency_probe_code = (
        "import importlib.metadata as md; import onnxruntime; "
        "from docling.document_converter import DocumentConverter; "
        "print('docling=' + md.version('docling') + "
        "' onnxruntime=' + md.version('onnxruntime'))"
    )

    def build_command(self, task: ProviderTask) -> dict[str, Any]:
        return super().build_command(task)
