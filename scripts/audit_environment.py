#!/usr/bin/env python3
"""只读检查 PDFFast 开发环境的文件闭包；不下载、不安装、不加载模型。

这是文件级清单检查，不是 Provider preflight、真实推理或 OCR 质量验收。
默认检查所有 runtime_enabled Provider；--profile 可限制到指定候选组合。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ROUTES = {
    "PAGE_DOCUMENT_OCR",
    "PAGE_DOCUMENT_LAYOUT_PARSE",
    "REGION_MULTIMODAL_PARSE",
    "INLINE_CONTEXT_PARSE",
}
LOCK_FILES = (
    "pyproject.toml",
    "uv.lock",
    "runtimes/mineru/pyproject.toml",
    "runtimes/mineru/uv.lock",
    "runtimes/marker/pyproject.toml",
    "runtimes/marker/uv.lock",
    "runtimes/docling/pyproject.toml",
    "runtimes/docling/uv.lock",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve(root: Path, raw: str) -> Path:
    expanded = os.path.expandvars(raw)
    if "$PDFFAST_PROJECT_ROOT" in expanded:
        expanded = expanded.replace("$PDFFAST_PROJECT_ROOT", str(root))
    path = Path(expanded).expanduser()
    return Path(os.path.abspath(path if path.is_absolute() else root / path))


def _record(items: list[dict[str, Any]], name: str, passed: bool, detail: str) -> None:
    items.append({"id": name, "status": "PASS" if passed else "MISSING_OR_INVALID", "detail": detail})


def _read_object(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: JSON 顶层必须是对象")
    return data


def _safe_relative(path: str) -> bool:
    candidate = Path(path)
    return bool(path) and not candidate.is_absolute() and ".." not in candidate.parts


def _profile_selection(path: Path, configs: dict[str, Any]) -> list[str]:
    data = _read_object(path)
    names = data.get("enabled_providers")
    routes = data.get("chains")
    if data.get("schema_version") != "1.0" or not isinstance(names, list):
        raise ValueError(f"{path}: Profile 必须声明 schema_version=1.0 和 enabled_providers")
    if not names or any(not isinstance(n, str) or not n for n in names):
        raise ValueError(f"{path}: enabled_providers 非法")
    if len(names) != len(set(names)) or not set(names) <= set(configs):
        raise ValueError(f"{path}: enabled_providers 含重复或未知名称")
    if not isinstance(routes, dict) or set(routes) != ROUTES:
        raise ValueError(f"{path}: Profile 必须覆盖全部四条 Capability Route")
    used: set[str] = set()
    for route in ROUTES:
        chain = routes[route]
        if (not isinstance(chain, list) or not chain
                or any(not isinstance(n, str) or n not in names for n in chain)
                or len(chain) != len(set(chain))):
            raise ValueError(f"{path}: {route} 路由候选非法")
        used.update(chain)
    if used != set(names):
        raise ValueError(f"{path}: enabled_providers 包含未使用 Provider")
    return sorted(names)


def _check_indra(
    root: Path, items: list[dict[str, Any]], *, hashes: bool
) -> None:
    base = root / "runtimes/indra"
    path = base / "install_manifest.json"
    _record(items, "indra:manifest", path.is_file(), str(path))
    if not path.is_file():
        return
    try:
        manifest = _read_object(path)
        model = Path(str(manifest.get("model_dir") or "")).resolve()
        expected_model = (base / "models/indra-ocr").resolve()
        revision = manifest.get("model_revision_sha")
        version = manifest.get("package_version")
        checksums = manifest.get("file_sha256")
        valid = (
            model == expected_model
            and isinstance(revision, str) and bool(re.fullmatch(r"[0-9a-f]{40}", revision))
            and isinstance(version, str) and bool(version)
            and isinstance(checksums, dict)
            and all(isinstance(n, str) and _safe_relative(n)
                    and isinstance(v, str) and re.fullmatch(r"[0-9a-f]{64}", v)
                    for n, v in checksums.items())
            and all(name in checksums for name in ("det.onnx", "rec_cjk.onnx", "order.onnx"))
        )
        _record(items, "indra:manifest-contract", valid,
                f"revision={revision}; model_dir={model}; package={version}")
        if not valid or not hashes:
            return
        for name, expected in sorted(checksums.items()):
            artifact = expected_model / name
            actual = sha256(artifact) if artifact.is_file() else None
            _record(items, f"indra:sha256:{name}", actual == expected, str(artifact))
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        _record(items, "indra:manifest-contract", False, f"{type(exc).__name__}: {exc}")


def audit(
    root: Path, *, profile: Path | None = None, hashes: bool = False,
) -> dict[str, Any]:
    root = root.expanduser().resolve()
    items: list[dict[str, Any]] = []
    for relative in LOCK_FILES:
        file = root / relative
        _record(items, f"lock:{relative}", file.is_file(), str(file))

    main_python = root / ".venv/bin/python"
    _record(items, "python:core", main_python.is_file(), str(main_python))

    config_path = root / "configs/providers.json"
    _record(items, "config:providers", config_path.is_file(), str(config_path))
    registry = _read_object(config_path) if config_path.is_file() else {}
    configs = registry.get("providers")
    if not isinstance(configs, dict):
        raise ValueError(f"{config_path}: 缺少 providers 对象")

    if profile is not None:
        profile_path = resolve(root, str(profile))
        selected = _profile_selection(profile_path, configs)
    else:
        profile_path = None
        selected = sorted(name for name, cfg in configs.items()
                          if isinstance(cfg, dict) and cfg.get("runtime_enabled") is True)

    for name in selected:
        cfg = configs[name]
        if not isinstance(cfg, dict):
            _record(items, f"provider:{name}:configuration", False, "Provider config 不是对象")
            continue
        if cfg.get("runtime_enabled") is not True:
            _record(items, f"provider:{name}:enabled", False, "runtime_enabled 不为 true")
            continue
        python_path = cfg.get("python_executable")
        if python_path:
            executable = resolve(root, str(python_path))
            _record(items, f"provider:{name}:python", executable.is_file(), str(executable))

        for raw in cfg.get("required_artifacts") or []:
            path = resolve(root, str(raw))
            _record(items, f"provider:{name}:artifact:{raw}", path.exists(), str(path))

        for raw, children in (cfg.get("required_artifact_trees") or {}).items():
            directory = resolve(root, str(raw))
            _record(items, f"provider:{name}:tree:{raw}", directory.is_dir(), str(directory))
            if not directory.is_dir():
                continue
            if not isinstance(children, list):
                _record(items, f"provider:{name}:tree-contract:{raw}", False,
                        "required_artifact_trees 的子文件必须是列表")
                continue
            for child in children:
                safe = isinstance(child, str) and _safe_relative(child)
                file = directory / child if safe else directory
                _record(items, f"provider:{name}:tree-file:{raw}/{child}",
                        safe and file.is_file(), str(file))

        for raw in cfg.get("required_artifact_manifests") or []:
            manifest_path = resolve(root, str(raw))
            _record(items, f"provider:{name}:external-manifest:{raw}",
                    manifest_path.is_file(), str(manifest_path))
            if manifest_path.is_file():
                try:
                    manifest = _read_object(manifest_path)
                    files = manifest.get("files")
                    if not isinstance(files, list):
                        raise ValueError("missing files[]")
                    for child in files:
                        safe = isinstance(child, str) and _safe_relative(child)
                        file = manifest_path.parent / child if safe else manifest_path.parent
                        _record(items, f"provider:{name}:external-file:{raw}/{child}",
                                safe and file.is_file(), str(file))
                except (OSError, ValueError, TypeError) as exc:
                    _record(items, f"provider:{name}:external-manifest-contract:{raw}",
                            False, str(exc))

        for raw, expected in (cfg.get("required_artifact_sha256") or {}).items():
            file = resolve(root, str(raw))
            if hashes:
                actual = sha256(file) if file.is_file() else None
                _record(items, f"provider:{name}:sha256:{raw}",
                        actual == str(expected).lower(), str(file))
        if name == "indra_local":
            _check_indra(root, items, hashes=hashes)

    try:
        proc = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                              capture_output=True, text=True, timeout=5, check=False)
        git_sha = proc.stdout.strip() if proc.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        git_sha = None

    failed = [item for item in items if item["status"] != "PASS"]
    return {
        "schema_version": "1.0",
        "audit_scope": "file_presence_and_optional_sha256_only",
        "root": str(root),
        "git_sha": git_sha,
        "provider_selection": "explicit_profile" if profile_path else "all_runtime_enabled",
        "profile": str(profile_path) if profile_path else None,
        "providers": selected,
        "hashes_checked": hashes,
        "checks": items,
        "summary": {"checked": len(items), "passed": len(items) - len(failed),
                    "failed": len(failed), "artifact_files_present": not failed},
        "not_checked": ["Provider preflight and startup", "real OCR execution",
                        "PDF parse quality", "model licensing", "external reference dataset"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--hashes", action="store_true",
                        help="验证注册的模型哈希及 Indra install manifest；可能读取大文件")
    parser.add_argument("--strict", action="store_true",
                        help="缺少任意文件或哈希不一致时返回非零退出码")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("--json-out", type=Path,
                        help="可选：将完整只读检查报告写到明确指定的文件")
    args = parser.parse_args()
    try:
        report = audit(args.root, profile=args.profile, hashes=args.hashes)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"环境清单检查失败：{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    if args.json_out:
        target = args.json_out.expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")

    if args.format == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        summary = report["summary"]
        print(f"PDFFast 文件级检查：{summary['passed']}/{summary['checked']} 通过，"
              f"{summary['failed']} 缺失/无效")
        print(f"检查 Provider：{', '.join(report['providers']) or '(无)'}")
        for item in report["checks"]:
            if item["status"] != "PASS":
                print(f"[MISSING] {item['id']}: {item['detail']}")
        print("注意：此工具不安装模型、不启动 Worker，不代表可推理/解析质量通过。")
        if not args.strict:
            print("清单模式只报告问题；正式门禁请使用 --strict。")

    return 1 if args.strict and report["summary"]["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
