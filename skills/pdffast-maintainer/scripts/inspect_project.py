#!/usr/bin/env python3
"""Read-only project inventory; no model imports."""
from __future__ import annotations
import argparse, hashlib, json, subprocess
from pathlib import Path

ROUTES = ("PAGE_DOCUMENT_OCR", "PAGE_DOCUMENT_LAYOUT_PARSE", "REGION_MULTIMODAL_PARSE", "INLINE_CONTEXT_PARSE")
REQUIRED = ("pdffast", "configs/providers.json", "tools/provider_benchmark/run.py",
            "tools/provider_benchmark/evaluate.py", "tools/provider_benchmark/report.py",
            "scripts/run_pipeline.py", "tests")

def git(root, *args):
    try:
        result = subprocess.run(["git", "-C", str(root), *args], capture_output=True,
                                text=True, timeout=8, check=False)
        return result.stdout.strip() if result.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None

def inspect(root):
    root = Path(root).resolve()
    missing = [p for p in REQUIRED if not (root / p).exists()]
    result = {"project_root": str(root), "valid_project": not missing,
              "missing_required": missing,
              "git": {"head": git(root, "rev-parse", "HEAD"),
                      "branch": git(root, "branch", "--show-current"),
                      "main": git(root, "rev-parse", "main"),
                      "working_tree_porcelain": git(root, "status", "--porcelain")},
              "available_docs": [x for x in ("README.md", "docs/PROVIDER_PLUGINS_ZH.md",
                  "docs/PROVIDER_BENCHMARK_ZH.md") if (root / x).is_file()]}
    config_path = root / "configs/providers.json"
    if config_path.is_file():
        try:
            data = config_path.read_bytes()
            registry = json.loads(data)
            providers = registry["providers"]
            if not isinstance(providers, dict):
                raise ValueError("providers not an object")
            result["registry"] = {"sha256": hashlib.sha256(data).hexdigest(),
                "schema": registry.get("schema_version"),
                "providers": {name: {"kind": p.get("kind"), "runtime_enabled": p.get("runtime_enabled"),
                    "benchmark_enabled": p.get("benchmark_enabled")}
                    for name, p in sorted(providers.items()) if isinstance(p, dict)},
                "plugins": sorted((registry.get("plugins") or {}).keys())}
        except (ValueError, KeyError, TypeError) as exc:
            result["registry_error"] = str(exc)
    profiles = {}
    for path in sorted((root / "configs/profiles").glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            chains, enabled = data["chains"], data["enabled_providers"]
            missing_routes = sorted(set(ROUTES) - set(chains))
            invalid = [r for r in ROUTES if r in chains and
                       (not isinstance(chains[r], list) or not chains[r] or
                        any(x not in enabled for x in chains[r]))]
            profiles[path.name] = {"valid": not missing_routes and not invalid,
                                   "missing_routes": missing_routes, "invalid": invalid}
        except (OSError, ValueError, KeyError, TypeError) as exc:
            profiles[path.name] = {"error": str(exc)}
    result["profiles"] = profiles
    result["warning"] = "Static inspection only; local main may be stale; no model inference performed."
    return result

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--project-root", required=True, type=Path)
    p.add_argument("--out", type=Path)
    a = p.parse_args()
    data = inspect(a.project_root)
    content = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(content, encoding="utf-8")
    print(content, end="")
    return 0 if data["valid_project"] and "registry_error" not in data else 2

if __name__ == "__main__":
    raise SystemExit(main())
