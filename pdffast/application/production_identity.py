"""Canonical configuration identity shared by production preflight and Core."""

from __future__ import annotations

import json
import os
import platform
import re
import subprocess
import sys
from collections.abc import Mapping
from hashlib import sha256
from pathlib import Path
from typing import Any

from pdffast.config import ParserConfig
from pdffast.providers.registry import DEFAULT_ADAPTER_PATHS

from .production_profile import ROOT, ProductionProfile

SCHEMA_VERSION = "1.0"
SEMANTIC_ENV_PREFIXES = (
    "MINERU_", "INDRA_", "ORT_", "OMP_", "MKL_", "OPENBLAS_", "VECLIB_",
    "HF_", "HUGGINGFACE_", "TRANSFORMERS_", "TORCH_", "PYTORCH_",
    "CUDA_", "MPS_", "UV_", "DYLD_", "LD_",
)


def digest(raw: bytes) -> str:
    return sha256(raw).hexdigest()


def fingerprint(value: Any) -> str:
    return digest(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False,
    ).encode("utf-8"))


def semantic_environment_digest(environment: Mapping[str, str]) -> str:
    return fingerprint({
        key: value for key, value in environment.items()
        if key.startswith(SEMANTIC_ENV_PREFIXES)
    })


def code_identity() -> dict[str, Any]:
    package = Path(__file__).resolve().parents[1]
    sources = {
        path.relative_to(package).as_posix(): digest(path.read_bytes())
        for path in sorted(package.rglob("*.py"))
    }
    if not sources or "application/production_identity.py" not in sources:
        raise ValueError("cannot identify loaded PDFFast package source")
    commit = None
    dirty = None
    if (ROOT / ".git").exists():
        # Git hooks and embedding applications can export a different checkout.
        git_env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        git_env["GIT_OPTIONAL_LOCKS"] = "0"

        def git(*args: str) -> str:
            return subprocess.run(
                ["git", "-C", str(ROOT), *args], capture_output=True, check=True,
                text=True, timeout=15, env=git_env,
            ).stdout.strip()

        if Path(git("rev-parse", "--show-toplevel")).resolve() != ROOT.resolve():
            raise ValueError("PDFFast code is not at the root of its Git checkout")
        commit = git("rev-parse", "HEAD")
        if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", commit):
            raise ValueError("invalid PDFFast Git revision")
        dirty = bool(git("status", "--porcelain=v1", "--untracked-files=all", "--",
                         "pdffast", "configs", "scripts/run_pipeline.py", "pyproject.toml", "uv.lock"))
        # Git's assume-unchanged / skip-worktree index bits can suppress status
        # output. Bind the production CLI's actual bytes directly to HEAD.
        cli_path = ROOT / "scripts/run_pipeline.py"
        try:
            committed_cli = subprocess.run(
                ["git", "-C", str(ROOT), "show", "HEAD:scripts/run_pipeline.py"],
                capture_output=True, check=True, timeout=15, env=git_env,
            ).stdout
            dirty = dirty or not cli_path.is_file() or cli_path.read_bytes() != committed_cli
        except (OSError, subprocess.SubprocessError):
            dirty = True
    algorithms = {}
    for label, directory in (
        ("native", "native"), ("evidence", "quality"), ("quality", "quality"),
        ("fallback_policy", "fallback"), ("canonical", "canonical"), ("renderer", "render"),
        ("audit", "audit"), ("structure_reconciliation", "structure_reconciliation"),
    ):
        relevant = {name: value for name, value in sources.items() if name.startswith(f"{directory}/")}
        if label in {"evidence", "quality"}:
            name = "quality/evidence.py" if label == "evidence" else "quality/gate.py"
            relevant = {name: sources[name]}
        algorithms[label] = fingerprint(relevant)
    return {
        "pdffast_commit": commit, "source_dirty": dirty,
        "source_sha256": fingerprint(sources), "algorithm_sha256": algorithms,
    }


def build_identity(
    snapshot: ProductionProfile, config: ParserConfig, runtimes: dict[str, Any],
    core_dependencies: dict[str, str],
) -> dict[str, Any]:
    code = code_identity()
    plugins = snapshot.registry.plugin_normalizers
    effective_configs = snapshot.configs
    routes = snapshot.chains
    allowed = list(snapshot.allowed)
    profile_hash = digest(snapshot.profile_bytes)
    providers_hash = digest(snapshot.providers_bytes)
    adapter_bindings = {}
    for name in allowed:
        kind = effective_configs[name]["kind"]
        plugin = snapshot.plugins.get(name)
        adapter_bindings[name] = plugin if plugin is not None else {
            "kind": kind,
            "factory": DEFAULT_ADAPTER_PATHS[kind],
            "normalizer": plugins.get(name) or "pdffast.providers.normalization:normalize_prediction",
        }
    semantic_input = {
        "schema_version": SCHEMA_VERSION,
        "profile_sha256": profile_hash,
        "providers_config_sha256": providers_hash,
        "route_candidates_sha256": digest(snapshot.candidates_bytes),
        "allowed_providers": allowed,
        "capability_routes": routes,
        "adapter_bindings": adapter_bindings,
        "provider_effective_config_sha256": {
            name: fingerprint(effective_configs[name]) for name in allowed
        },
        "code_identity": {
            key: value for key, value in code.items() if key != "source_dirty"
        },
        "parser_options": {
            "page_dpi": config.page_dpi,
            "region_dpi": config.region_dpi,
            "table_mode": config.table_mode,
        },
        "runtime_identity": {name: runtimes[name].get("identity") for name in allowed},
        "core_dependencies": core_dependencies,
        "host": {
            "platform": sys.platform, "machine": platform.machine(),
            "platform_release": platform.release(),
            "python": platform.python_version(),
        },
        "semantic_env_sha256": semantic_environment_digest(snapshot.environment),
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "profile_locked": True,
        "profile_name": snapshot.name,
        "profile_path": str(snapshot.profile_path),
        "profile_sha256": profile_hash,
        "providers_config_path": snapshot.providers_path,
        "providers_config_sha256": providers_hash,
        "pdffast_commit": code["pdffast_commit"],
        "code_identity": code,
        "allowed_providers": allowed,
        "capability_routes": routes,
        "fingerprint_input": semantic_input,
        "effective_config_fingerprint": fingerprint(semantic_input),
    }
