"""Opt-in MiniCPM-OCR 1.0 single-image recognition Provider.

Uses the official OpenAI-compatible image + 'Text Recognition:' interface.
It is NOT the MiniCPM SDK full-document layout pipeline, and it is NOT Jev.
No external model is installed or started by this adapter.
"""

from __future__ import annotations

import base64
import json
import os
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from .base import ProviderPreflight, ProviderTask, RawProviderResult


class MiniCPMOCRProvider:
    def __init__(
        self,
        name: str,
        config: dict[str, Any],
        *,
        opener: Callable[..., Any] | None = None,
    ) -> None:
        self.name = name
        self.config = dict(config)
        self._opener = opener or urlopen
        self.base_url = str(self.config.get("base_url") or "http://127.0.0.1:18499/v1").rstrip("/")
        parts = urlsplit(self.base_url)
        if (
            parts.scheme not in {"http", "https"}
            or not parts.hostname or parts.query or parts.fragment
            or parts.username or parts.password
            or not parts.path.endswith("/v1")
        ):
            raise ValueError("MiniCPM base_url must be an HTTP(S) URL ending in /v1")
        local = parts.hostname in {"127.0.0.1", "localhost", "::1"}
        if not local and self.config.get("allow_remote") is not True:
            raise ValueError(
                "MiniCPM OCR input contains document images; non-local endpoint requires "
                "explicit allow_remote=true"
            )
        self.model = str(self.config.get("model") or "minicpm-ocr")
        self.prompt = str(self.config.get("prompt") or "Text Recognition:")
        if self.prompt not in {
            "Text Recognition:", "Table Recognition:",
            "Formula Recognition:", "Seal Recognition:", "Chart to Table:",
        }:
            raise ValueError("MiniCPM prompt must be one of the official recognition tasks")
        self.timeout_seconds = float(self.config.get("timeout_seconds", 300))
        self.preflight_timeout_seconds = float(self.config.get("preflight_timeout_seconds", 8))
        self.max_tokens = int(self.config.get("max_tokens", 2048))
        self.max_image_bytes = int(self.config.get("max_image_bytes", 24 * 1024 * 1024))
        if not 1 <= self.timeout_seconds <= 3600:
            raise ValueError("timeout_seconds must be 1..3600")
        if not 1 <= self.preflight_timeout_seconds <= 120:
            raise ValueError("preflight_timeout_seconds must be 1..120")
        if not 1 <= self.max_tokens <= 32768 or not 1 <= self.max_image_bytes <= 100 * 1024 * 1024:
            raise ValueError("invalid MiniCPM generation/image limits")
        self._api_key_env = str(self.config.get("api_key_env") or "").strip()

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self._api_key_env:
            secret = os.environ.get(self._api_key_env)
            if not secret:
                raise ValueError(f"MiniCPM API credential environment variable not set: {self._api_key_env}")
            headers["Authorization"] = "Bearer " + secret
        return headers

    def _request_json(
        self,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        timeout: float,
    ) -> dict[str, Any]:
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
        request = Request(
            self.base_url + path,
            data=encoded,
            headers=self._headers(),
            method="POST" if encoded is not None else "GET",
        )
        with self._opener(request, timeout=timeout) as response:
            body = response.read(16 * 1024 * 1024 + 1)
        if len(body) > 16 * 1024 * 1024:
            raise ValueError("MiniCPM service response exceeded 16 MiB")
        obj = json.loads(body)
        if not isinstance(obj, dict):
            raise ValueError("MiniCPM service must return a JSON object")
        return obj

    def preflight(self) -> ProviderPreflight:
        try:
            data = self._request_json("/models", timeout=self.preflight_timeout_seconds)
            models = data.get("data")
            if not isinstance(models, list):
                raise ValueError("invalid /v1/models response (missing data[])")
            ids = {
                str(item.get("id")) for item in models if isinstance(item, dict) and item.get("id")
            }
            if self.model not in ids:
                raise ValueError(f"model {self.model!r} not served; available={sorted(ids)}")
            return ProviderPreflight(
                self.name, True, f"MiniCPM model={self.model} available",
                {"backend": "openai_compatible", "mode": "single_image_recognition"},
            )
        except Exception as exc:
            return ProviderPreflight(
                self.name, False,
                f"{type(exc).__name__}: {exc}",
            )

    def initialize(self) -> None:
        """The server is launched separately; this adapter owns no subprocess."""
        return None

    def execute(self, task: ProviderTask) -> RawProviderResult:
        path = Path(task.input_image)
        suffix = path.suffix.lower()
        media_type = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}.get(suffix)
        if media_type is None:
            raise ValueError("MiniCPM direct recognition requires a PNG/JPEG/WebP image, not a PDF")
        image_bytes = path.read_bytes()
        if not image_bytes or len(image_bytes) > self.max_image_bytes:
            raise ValueError("MiniCPM image is empty or exceeds max_image_bytes")

        payload = {
            "model": self.model,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {
                        "url": f"data:{media_type};base64," + base64.b64encode(image_bytes).decode("ascii"),
                    }},
                    {"type": "text", "text": self.prompt},
                ],
            }],
            "temperature": 0.01, "top_p": 0.001,
            "max_tokens": self.max_tokens,
            "stream": False,
        }
        started = time.perf_counter()
        response = self._request_json("/chat/completions", payload=payload, timeout=self.timeout_seconds)
        elapsed = time.perf_counter() - started
        choices = response.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise ValueError("MiniCPM response missing choices[0]")
        choice = choices[0]
        message = choice.get("message")
        if not isinstance(message, dict):
            raise ValueError("MiniCPM response missing message")
        content = message.get("content")
        if not isinstance(content, str):
            raise ValueError("MiniCPM response message.content must be text")
        text = content.strip()
        if not text:
            raise ValueError("MiniCPM OCR returned empty text")
        finish_reason = choice.get("finish_reason")
        truncated = finish_reason == "length"
        warnings: tuple[str, ...] = ("OUTPUT_TRUNCATED",) if truncated else ()
        return RawProviderResult(
            provider=self.name,
            task_id=task.task_id,
            status="SUCCESS_WITH_WARNINGS" if truncated else "SUCCESS",
            payload={
                "provider_kind": "minicpm_ocr_api",
                "model_or_engine": self.model,
                "text": text,
                "confidence": None,
                "warnings": list(warnings),
                "structure": {
                    "recognition_mode": "single_image_region",
                    "prompt": self.prompt,
                    "finish_reason": finish_reason,
                    "usage": response.get("usage"),
                    "layout_reconstruction": "NOT_PERFORMED",
                    "reading_order": "NOT_VERIFIED",
                    "table_structure": "NOT_VERIFIED",
                },
            },
            markdown=text,
            elapsed_seconds=elapsed,
            warnings=warnings,
        )

    def close(self) -> None:
        """The external server remains up for other benchmark runs."""
        return None
