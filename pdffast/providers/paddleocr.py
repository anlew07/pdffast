from __future__ import annotations

import importlib
import os
import statistics
from collections.abc import Callable
from typing import Any

from .base import ProviderPreflight, ProviderTask, RawProviderResult


def _result_json(value: Any) -> Any:
    payload = getattr(value, "json", None)
    if callable(payload):
        payload = payload()
    return payload


def _result_markdown(value: Any) -> str:
    markdown = getattr(value, "markdown", "")
    if callable(markdown):
        markdown = markdown()
    if isinstance(markdown, dict):
        markdown = markdown.get("markdown_texts") or markdown.get("text") or ""
    return str(markdown or "")


def _find_lists(value: Any, key: str) -> list[Any]:
    if isinstance(value, dict):
        candidate = value.get(key)
        if isinstance(candidate, list):
            return candidate
        for child in value.values():
            found = _find_lists(child, key)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_lists(child, key)
            if found:
                return found
    return []


class _PaddleProvider:
    engine_class = ""
    markdown_output = False

    def __init__(
        self,
        name: str,
        config: dict[str, Any],
        *,
        engine_factory: Callable[[dict[str, Any]], Any] | None = None,
        dependency_probe: Callable[[], tuple[bool, str]] | None = None,
    ) -> None:
        self.name = name
        self.config = dict(config)
        self._engine_factory = engine_factory or self._default_factory
        self._dependency_probe = dependency_probe or self._default_probe
        self._engine: Any = None
        self._closed = False

    def _default_probe(self) -> tuple[bool, str]:
        try:
            module = importlib.import_module("paddleocr")
            getattr(module, self.engine_class)
            return True, f"paddleocr={getattr(module, '__version__', 'unknown')} {self.engine_class}=ok"
        except Exception as exc:
            return False, f"{type(exc).__name__}: {exc}"

    def _default_factory(self, config: dict[str, Any]) -> Any:
        module = importlib.import_module("paddleocr")
        engine_class = getattr(module, self.engine_class)
        extra_options = config.get("init_options") or {}
        if not isinstance(extra_options, dict):
            raise ValueError(f"provider={self.name} init_options must be an object")
        keys_by_engine = {
            "PaddleOCR": (
                "lang",
                "ocr_version",
                "device",
                "use_doc_orientation_classify",
                "use_doc_unwarping",
                "use_textline_orientation",
                "text_detection_model_name",
                "text_detection_model_dir",
                "text_recognition_model_name",
                "text_recognition_model_dir",
            ),
            "PaddleOCRVL": (
                "device",
                "engine",
                "vl_rec_backend",
                "vl_rec_server_url",
                "vl_rec_api_model_name",
                "vl_rec_max_concurrency",
                "layout_detection_model_name",
                "layout_detection_model_dir",
                "vl_rec_model_name",
                "vl_rec_model_dir",
            ),
            "PPStructureV3": ("device", "engine", "lang"),
        }
        options = {
            key: config[key]
            for key in keys_by_engine[self.engine_class]
            if config.get(key) is not None
        }
        if self.engine_class == "PaddleOCRVL":
            options["pipeline_version"] = config.get("pipeline_version", "v1.6")
            api_key_env = config.get("vl_rec_api_key_env")
            if api_key_env and os.environ.get(str(api_key_env)):
                options["vl_rec_api_key"] = os.environ[str(api_key_env)]
        options.update(extra_options)
        return engine_class(**options)

    def preflight(self) -> ProviderPreflight:
        available, detail = self._dependency_probe()
        return ProviderPreflight(self.name, available, detail)

    def initialize(self) -> None:
        if self._engine is None:
            self._engine = self._engine_factory(self.config)
            self._closed = False

    def execute(self, task: ProviderTask) -> RawProviderResult:
        self.initialize()
        options = self.config.get("predict_options") or {}
        if not isinstance(options, dict):
            raise ValueError(f"provider={self.name} predict_options must be an object")
        outputs = list(self._engine.predict(input=str(task.input_image), **options))
        payloads = [_result_json(item) for item in outputs]
        markdown = "\n\n".join(filter(None, (_result_markdown(item) for item in outputs))).strip()
        scores: list[float] = []
        if self.markdown_output:
            text = markdown
        else:
            texts: list[str] = []
            for payload in payloads:
                texts.extend(str(value) for value in _find_lists(payload, "rec_texts"))
                scores.extend(float(value) for value in _find_lists(payload, "rec_scores"))
            text = "\n".join(value.strip() for value in texts if value.strip())
        warnings = tuple(
            reason
            for reason, needed in (
                ("PROVIDER_RETURNED_NO_RESULTS", not outputs),
                ("EMPTY_TEXT", not text),
            )
            if needed
        )
        return RawProviderResult(
            provider=self.name,
            task_id=task.task_id,
            status="SUCCESS",
            payload={
                "text": text,
                "confidence": statistics.mean(scores) if scores else None,
                "warnings": list(warnings),
                "structure": {"ocr_line_count": len(scores)} if not self.markdown_output else {},
                "raw": payloads,
            },
            markdown=markdown or None,
            warnings=warnings,
        )

    def close(self) -> None:
        if self._closed:
            return
        self._engine = None
        self._closed = True


class PaddleOCRTextProvider(_PaddleProvider):
    engine_class = "PaddleOCR"


class PaddleOCRVLProvider(_PaddleProvider):
    engine_class = "PaddleOCRVL"
    markdown_output = True


class PPStructureV3Provider(_PaddleProvider):
    engine_class = "PPStructureV3"
    markdown_output = True
