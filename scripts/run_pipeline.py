#!/usr/bin/env python3
"""Run the PDFFast Core pipeline from PDF to final Markdown."""

from __future__ import annotations

import argparse
import json
import sys
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path

if __name__ == "__main__" and not __package__:
    # Resolve the package from this script's checkout in direct-script mode.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pdffast import ConfigurationError, PDFFastParser, PDFFastError, ParseExecutionError
from pdffast.application.execution_contract import REQUEST_SCHEMA_VERSION
from pdffast.runtime import ParseCancelledError


def _run_embedded(args: argparse.Namespace) -> int:
    request = {
        "schema_version": REQUEST_SCHEMA_VERSION,
        "run_id": args.run_id,
        "input": {"sha256": args.expected_input_sha256},
        "options": {},
    }
    try:
        if args.provider_config is not None:
            raise ConfigurationError("the embedded entry point uses a deployment profile")
        parser = PDFFastParser(
            project_root=args.project_root,
            output_root=args.output_root,
            provider_profile=args.provider_profile,
        )
        with redirect_stdout(sys.stderr):
            result = parser.parse_request(args.pdf, request, case_id=args.case_id)
        response = result.execution_contract
        if response is None:
            raise ParseExecutionError("locked parse returned no execution contract")
    except (PDFFastError, ParseCancelledError) as exc:
        response = exc.to_contract(run_id=args.run_id)
    except Exception as exc:
        error = ParseExecutionError(
            "unexpected embedded entry point failure", stage="embedded_entry",
            details={"cause_type": type(exc).__name__},
        )
        response = error.to_contract(run_id=args.run_id)

    print(json.dumps(response, ensure_ascii=False, allow_nan=False))
    return {
        "SUCCESS": 0, "BLOCKED": 2, "FAILED": 3, "PARTIAL_SUCCESS": 4, "CANCELLED": 5,
    }[response["status"]]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run PDFFast Core PDF pipeline")
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output-root", type=Path, default=Path("outputs"))
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--case-id", default=None)
    parser.add_argument("--provider-config", type=Path, default=None)
    parser.add_argument("--provider-profile", type=Path, default=None, help="Local production profile JSON; complete four-route override")
    parser.add_argument(
        "--expected-input-sha256",
        help="Enable the Embedded JSON contract with this caller-supplied SHA-256 (requires --run-id and --provider-profile)",
    )
    args = parser.parse_args()
    if args.expected_input_sha256 is not None:
        return _run_embedded(args)
    if not args.pdf.is_file():
        parser.error(f"PDF 不存在: {args.pdf}")
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
