"""Create a benchmark-only Provider config with opt-in MiniCPM-OCR 1.0.

Does not alter configs/providers.json or enable any new production route.
"""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path
from typing import Any


PLUGIN_NAME = "minicpm_ocr_local"
PLUGIN_SPEC = {
    "kind": "minicpm_ocr_api",
    "factory": "pdffast.providers.minicpm_ocr:MiniCPMOCRProvider",
    "normalizer": "pdffast.providers.minicpm_normalizer:normalize",
}


def with_minicpm(
    config: dict[str, Any],
    *,
    base_url: str = "http://127.0.0.1:18499/v1",
    model: str = "minicpm-ocr",
    max_tokens: int = 2048,
) -> dict[str, Any]:
    if not isinstance(config, dict) or not isinstance(config.get("providers"), dict):
        raise ValueError("base Provider config must contain providers{}")
    result = deepcopy(config)
    providers = result["providers"]
    plugins = result.setdefault("plugins", {})
    if not isinstance(plugins, dict):
        raise ValueError("base Provider config plugins must be an object")
    if PLUGIN_NAME in providers or PLUGIN_NAME in plugins:
        raise ValueError(f"{PLUGIN_NAME} already registered; do not overwrite it")
    plugins[PLUGIN_NAME] = dict(PLUGIN_SPEC)
    providers[PLUGIN_NAME] = {
        "kind": PLUGIN_SPEC["kind"],
        "runtime_enabled": False,
        "benchmark_enabled": True,
        "benchmark_input": "image",
        "base_url": base_url,
        "model": model,
        "prompt": "Text Recognition:",
        "max_tokens": max_tokens,
        "timeout_seconds": 300,
        "preflight_timeout_seconds": 8,
        "max_image_bytes": 24 * 1024 * 1024,
        "allow_remote": False,
    }
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description="Extend local PDFFast Benchmark config with MiniCPM-OCR plugin")
    ap.add_argument("--base", type=Path, default=Path("configs/providers.json"))
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--base-url", default="http://127.0.0.1:18499/v1")
    ap.add_argument("--model", default="minicpm-ocr")
    ap.add_argument("--max-tokens", type=int, default=2048)
    args = ap.parse_args()
    base_config = json.loads(args.base.read_text(encoding="utf-8"))
    config = with_minicpm(
        base_config, base_url=args.base_url,
        model=args.model, max_tokens=args.max_tokens,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Created benchmark-only Provider config: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
