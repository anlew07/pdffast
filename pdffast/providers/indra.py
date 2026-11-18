"""Indra OCR: persistent isolated runtime adapter for V3 fallback units.

Stage 8/9 decides *which* raster crops need OCR. This adapter never reclassifies
the PDF or OCRs pages outside those tasks. The model is loaded lazily once per
persistent worker and reused across fallback tasks.
"""
from __future__ import annotations

from .workers import IsolatedWorkerProvider

WORKER_CODE = r'''
from __future__ import annotations
import contextlib
import hashlib
import json
import sys
import time
import traceback
from pathlib import Path

protocol_stdout = sys.stdout

def send(obj):
    protocol_stdout.write(json.dumps(obj, ensure_ascii=False, default=str) + "\n")
    protocol_stdout.flush()

try:
    with contextlib.redirect_stdout(sys.stderr):
        import indra_ocr
    send({"status": "READY", "engine": "indra-ocr", "version": indra_ocr.__version__})
except BaseException as exc:
    send({"status": "INIT_FAILED", "error": f"{type(exc).__name__}: {exc}"})
    raise

converters = {}
for raw_line in sys.stdin:
    try:
        msg = json.loads(raw_line)
        op = msg.get("op")
        if op == "close":
            send({"status": "BYE"})
            break
        if op == "ping":
            send({"status": "PONG", "nonce": msg.get("nonce")})
            continue
        if op != "parse":
            send({"status": "FAILED", "error": "unsupported operation"})
            continue
        started = time.perf_counter()
        input_image = Path(str(msg["input"])).resolve()
        if not input_image.is_file():
            raise FileNotFoundError(input_image)
        model_dir = Path(str(msg["model_dir"])).resolve()
        if not (model_dir / "det.onnx").is_file():
            raise FileNotFoundError(model_dir / "det.onnx")
        threads = int(msg.get("threads", 4))
        if threads < 1 or threads > 64:
            raise ValueError("threads must be between 1 and 64")
        math = bool(msg.get("math", False))
        furniture = bool(msg.get("furniture", True))
        key = (str(model_dir), threads, math, furniture)
        with contextlib.redirect_stdout(sys.stderr):
            if key not in converters:
                converters[key] = indra_ocr.load(
                    path=str(model_dir), threads=threads, mode="ocr",
                    furniture=furniture, math=math,
                )
            pages = list(converters[key].convert(str(input_image)))
        if len(pages) != 1:
            raise RuntimeError(f"expected one crop/page, got {len(pages)}")
        # Indra 1.1.2 Converter.convert() yields (page_index, Page), not Page.
        # Silently treating the tuple as Page previously made every OCR result
        # SUCCESS with empty markdown, so all tasks escalated to RapidOCR.
        converted = pages[0]
        if (not isinstance(converted, tuple) or len(converted) != 2
                or converted[0] != 0):
            raise RuntimeError(
                "unexpected Indra convert() response; expected (0, Page)"
            )
        page_index, page = converted
        if not all(hasattr(page, name) for name in ("markdown", "text", "lines", "source")):
            raise TypeError("unexpected Indra Page payload; missing OCR output fields")
        if page.source == "error":
            raise RuntimeError(str(getattr(page, "note", "Indra page error")))
        markdown = str(getattr(page, "markdown", None) or getattr(page, "text", None) or "")
        plain_text = str(getattr(page, "text", None) or "")
        output_dir = Path(str(msg["output_dir"])).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        suffix = hashlib.sha256(str(msg["task_id"]).encode("utf-8")).hexdigest()[:16]
        md_file = output_dir / f"indra_{suffix}.md"
        json_file = output_dir / f"indra_{suffix}.json"
        lines = [
            {"box": list(getattr(line, "box", ()) or ()),
             "text": str(getattr(line, "text", "") or ""),
             "conf": getattr(line, "conf", None)}
            for line in (getattr(page, "lines", None) or ())
        ]
        record = {
            "task_id": msg["task_id"], "plain_text": plain_text,
            "markdown": markdown, "source": getattr(page, "source", None),
            "lines": lines, "blocks": getattr(page, "blocks", None) or [],
            "rotation": getattr(page, "rotation", None),
            "skew": getattr(page, "skew", None),
            "timings": getattr(page, "timings", None) or {},
        }
        md_file.write_text(markdown, encoding="utf-8")
        json_file.write_text(json.dumps(record, ensure_ascii=False, default=str, indent=2) + "\n", encoding="utf-8")
        send({
            "status": "SUCCESS", "markdown_path": str(md_file),
            "raw_refs": [str(md_file), str(json_file)],
            "plain_text": plain_text, "lines": lines,
            "source": record["source"], "elapsed_seconds": time.perf_counter() - started,
        })
    except BaseException as exc:
        send({"status": "FAILED", "error": f"{type(exc).__name__}: {exc}",
              "traceback": traceback.format_exc()})
'''

class IndraProvider(IsolatedWorkerProvider):
    """Use runtimes/indra/.venv, never the pdffast or JudgeAI Python env."""

    default_python = "runtimes/indra/.venv/bin/python"
    result_path_key = "markdown_path"
    worker_code = WORKER_CODE
    dependency_probe_code = (
        "import indra_ocr; print('indra-ocr=' + indra_ocr.__version__)"
    )

    def build_command(self, task):
        from pathlib import Path
        command = super().build_command(task)
        model_dir = Path(str(self.config.get("model_dir") or "runtimes/indra/models/indra-ocr"))
        if not model_dir.is_absolute():
            model_dir = Path(__file__).resolve().parents[2] / model_dir
        command.update({
            "task_id": task.task_id,
            "model_dir": str(model_dir),
            "threads": int(self.config.get("threads", 4)),
            "math": bool(self.config.get("math", False)),
            "furniture": bool(self.config.get("furniture", True)),
        })
        return command
