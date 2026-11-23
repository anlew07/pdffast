#!/usr/bin/env python3
"""Run the PDFFast Core pipeline from PDF to final Markdown."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from pdffast import PDFFastParser


def main() -> int:
    parser = argparse.ArgumentParser(description="Run PDFFast Core PDF pipeline")
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output-root", type=Path, default=Path("outputs"))
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--case-id", default=None)
    parser.add_argument("--provider-config", type=Path, default=None)
    parser.add_argument("--provider-profile", type=Path, default=None, help="Local production profile JSON; complete four-route override")
    args = parser.parse_args()
    if not args.pdf.is_file():
        parser.error(
            f"PDF 不存在: {args.pdf}. 若要只处理已有 Stage 1-9 artifact，"
            "请使用 --from-artifacts（当前 CLI 尚未启用该模式）。"
        )
    run_id = args.run_id or datetime.now(timezone.utc).strftime("run_%Y%m%dT%H%M%SZ")
    if args.provider_profile is not None and args.provider_config is not None:
        parser.error("--provider-profile cannot be combined with --provider-config")
    config = {}
    if args.provider_profile is None:
        config_path = args.provider_config or args.project_root / "configs/providers.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        if not isinstance(config.get("providers"), dict):
            parser.error(f"provider config missing providers object: {config_path}")

    result = PDFFastParser(
        project_root=args.project_root,
        output_root=args.output_root,
        provider_configs=config.get("providers"),
        provider_plugins=config.get("plugins"),
        provider_chain_overrides=None if args.provider_profile else config.get("provider_chain_overrides"),
        provider_profile=args.provider_profile,
    ).parse(args.pdf, run_id=run_id, case_id=args.case_id)
    # The actual document and evidence already exist on disk. Never dump
    # canonical JSON or the entire Markdown body to a terminal/CI log.
    audit_pass = result["structure_audit"]["validation"]["pass"] is True
    execution_status = (
        result.parser_provenance["execution_status"]
        if args.provider_profile is not None else "COMPLETED"
    )
    final_status = "AUDIT_FAILED" if not audit_pass else (
        "PASS" if execution_status == "COMPLETED" else execution_status
    )
    print(f"Run ID: {run_id}")
    print(f"Status: {final_status}")
    print(f"Canonical JSON: {result['result_document']}")
    print(f"Markdown: {result['result_markdown']}")
    print(f"Audit JSON: {result['result_audit']}")
    print(f"Manifest: {result['result_manifest']}")
    return 0 if final_status == "PASS" else (2 if final_status == "AUDIT_FAILED" else 3)


if __name__ == "__main__":
    raise SystemExit(main())
