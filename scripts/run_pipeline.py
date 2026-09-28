#!/usr/bin/env python3
"""Run the PDFFast Core pipeline from PDF to final Markdown."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from pdffast import PDFFastParser
from pdffast.providers.runtime_normalization import normalize_runtime_result
from pdffast.providers.registry import ProviderRegistry


def main() -> int:
    parser = argparse.ArgumentParser(description="Run PDFFast Core PDF pipeline")
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output-root", type=Path, default=Path("outputs"))
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--case-id", default=None)
    parser.add_argument("--provider-config", type=Path, default=None)
    args = parser.parse_args()
    if not args.pdf.is_file():
        parser.error(
            f"PDF 不存在: {args.pdf}. 若要只处理已有 Stage 1-9 artifact，"
            "请使用 --from-artifacts（当前 CLI 尚未启用该模式）。"
        )
    run_id = args.run_id or datetime.now(timezone.utc).strftime("run_%Y%m%dT%H%M%SZ")
    config_path = args.provider_config or args.project_root / "configs/providers.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    provider_configs = config.get("providers")
    if not isinstance(provider_configs, dict):
        parser.error(f"provider config missing providers object: {config_path}")
    registry = ProviderRegistry(base_dir=args.project_root)

    result = PDFFastParser(
        project_root=args.project_root,
        output_root=args.output_root,
        provider_configs=provider_configs,
        registry=registry,
        normalizer=normalize_runtime_result,
    ).parse(args.pdf, run_id=run_id, case_id=args.case_id)
    print(f"Canonical: {result['canonical']}")
    print(f"Markdown: {result['markdown']}")
    print(f"Structure audit: {result['structure_audit']}")
    return 0 if result["structure_audit"]["validation"]["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
