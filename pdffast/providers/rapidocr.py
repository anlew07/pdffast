from __future__ import annotations

import importlib
import statistics
from collections.abc import Callable
from typing import Any

from .base import ProviderPreflight, ProviderTask, RawProviderResult


DependencyProbe = Callable[[], tuple[bool, str]]
EngineFactory = Callable[[dict[str, Any]], Any]


def _default_probe() -> tuple[bool, str]:
    try:
        module = importlib.import_module("rapidocr")
        getattr(module, "RapidOCR")
        return True, f"rapidocr={getattr(module, '__version__', 'unknown')}"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def _default_factory(config: dict[str, Any]) -> Any:
    module = importlib.import_module("rapidocr")
    params = config.get("params") or {}
    if not isinstance(params, dict):
        raise ValueError("RapidOCR params must be an object")
    config_path = config.get("config_path")
    return module.RapidOCR(
        config_path=str(config_path) if config_path else None,
        params=params or None,
    )


class RapidOCRProvider:
    def __init__(
        self,
        name: str,
        config: dict[str, Any],
        *,
        engine_factory: EngineFactory | None = None,
        dependency_probe: DependencyProbe | None = None,
    ) -> None:
        self.name = name
        self.config = dict(config)
        self._engine_factory = engine_factory or _default_factory
        self._dependency_probe = dependency_probe or _default_probe
        self._engine: Any = None
        self._closed = False

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
        allowed = {
            "use_det",
            "use_cls",
            "use_rec",
            "return_word_box",
            "return_single_char_box",
            "text_score",
            "box_thresh",
            "unclip_ratio",
        }
        call_options = {key: value for key, value in options.items() if key in allowed}
        result = self._engine(str(task.input_image), **call_options)
        texts = [str(value) for value in (getattr(result, "txts", None) or [])]
        scores = [float(value) for value in (getattr(result, "scores", None) or [])]
        raw_boxes = getattr(result, "boxes", None)
        boxes = raw_boxes.tolist() if hasattr(raw_boxes, "tolist") else raw_boxes
        boxes = boxes if isinstance(boxes, list) else []
        spatial_items: list[dict[str, Any]] = []
        for index, value in enumerate(texts):
            text = value.strip()
            if not text:
                continue
            polygon = boxes[index] if index < len(boxes) else []
            polygon = polygon if isinstance(polygon, list) else []
            spatial_items.append(
                {
                    "item_id": f"ocr_{len(spatial_items) + 1:03d}",
                    "text": text,
                    "confidence": scores[index] if index < len(scores) else None,
                    "polygon": polygon,
                    "provider_order": index,
                }
            )
        text = "\n".join(value.strip() for value in texts if value.strip())
        warnings = () if text else ("EMPTY_TEXT",)
        payload = {
            "text": text,
            "confidence": statistics.mean(scores) if scores else None,
            "warnings": list(warnings),
            "structure": {
                "ocr_line_count": len(texts),
                "box_count": len(boxes),
                "spatial_text_items": spatial_items,
                "spatial_text_semantics": "OCR_GEOMETRY_ONLY_NO_READING_ORDER_NO_RELATIONS",
                "provider_elapse_seconds": getattr(result, "elapse", None),
                "provider_stage_elapse_seconds": getattr(result, "elapse_list", None),
            },
            "raw": {
                "txts": texts,
                "scores": scores,
                "boxes": boxes,
                "elapse": getattr(result, "elapse", None),
                "elapse_list": getattr(result, "elapse_list", None),
            },
        }
        return RawProviderResult(
            provider=self.name,
            task_id=task.task_id,
            status="SUCCESS",
            payload=payload,
            elapsed_seconds=getattr(result, "elapse", None),
            warnings=warnings,
        )

    def close(self) -> None:
        if self._closed:
            return
        self._engine = None
        self._closed = True
