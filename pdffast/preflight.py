"""Command line interface for production profile preflight."""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
from pathlib import Path

from pdffast.application.production_identity import SCHEMA_VERSION
from pdffast.application.production_preflight import preflight_production_profile


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        print(json.dumps({
            "schema_version": SCHEMA_VERSION, "status": "CONFIGURATION_FAILED", "error": message,
        }), flush=True)
        raise SystemExit(2)


def main() -> int:
    parser = JsonArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path)
    parser.add_argument("--provider-profile", type=Path, required=True)
    parser.add_argument("--json", action="store_true", help="emit the V1 JSON report (default)")
    parser.add_argument("--probe", action="store_true", help="also run dependency probes, without inference")
    args = parser.parse_args()
    with contextlib.redirect_stdout(sys.stderr):
        report = preflight_production_profile(
            project_root=args.project_root, provider_profile=args.provider_profile, probe=args.probe,
        )
    print(json.dumps(report, ensure_ascii=False, allow_nan=False, sort_keys=True), flush=True)
    return {"PASS": 0, "CONFIGURATION_FAILED": 2, "PREFLIGHT_FAILED": 3}[report["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
