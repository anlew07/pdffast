#!/usr/bin/env python3
"""Freeze SHA-256 and filesystem identities for installed production model assets.

Run once after installing the approved Indra and MinerU model revisions. This
reads local files only; it never downloads or changes model contents.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import string
import tempfile
from pathlib import Path
from typing import Any


def sha256(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def stat_identity(path: Path) -> dict[str, int]:
    value = path.stat()
    return {
        "size": value.st_size,
        "mtime_ns": value.st_mtime_ns,
        "ctime_ns": value.st_ctime_ns,
        "inode": value.st_ino,
        "device": value.st_dev,
        "mode": stat.S_IMODE(value.st_mode),
        "uid": value.st_uid,
        "gid": value.st_gid,
    }


def resolve(root: Path, value: str) -> Path:
    expanded = string.Template(value).safe_substitute(
        {"HOME": str(Path.home()), "PDFFAST_PROJECT_ROOT": str(root)}
    )
    path = Path(expanded).expanduser()
    return path if path.is_absolute() else (root / path).resolve()


def write_manifest(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".asset-manifest-", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o444)
        os.replace(temporary, path)
        descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def freeze_indra(root: Path, config: dict[str, Any]) -> Path:
    provider = config["providers"]["indra_local"]
    model_dir = resolve(root, provider["model_dir"])
    install_manifest = model_dir.parents[1] / "install_manifest.json"
    record = json.loads(install_manifest.read_bytes())
    revision = record.get("model_revision_sha")
    declared = record.get("file_sha256")
    if not isinstance(revision, str) or not isinstance(declared, dict) or not declared:
        raise ValueError("Indra install manifest lacks a revision or file SHA-256 map")
    files = {}
    for name, expected in sorted(declared.items()):
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts or not isinstance(expected, str):
            raise ValueError(f"invalid Indra model manifest entry: {name!r}")
        path = model_dir / relative
        actual = sha256(path)
        if actual != expected:
            raise ValueError(f"Indra model SHA-256 mismatch: {name}")
        files[name] = {"sha256": actual, "stat": stat_identity(path)}
    output = resolve(root, provider["model_asset_manifest"])
    write_manifest(output, {
        "schema_version": "1.0", "provider": "indra_local", "revision": revision,
        "tools_config_sha256": None, "files": files,
    })
    return output


def freeze_mineru(root: Path, config: dict[str, Any]) -> Path:
    provider = config["providers"]["mineru_local"]
    raw_config_path = resolve(root, provider["env"]["MINERU_TOOLS_CONFIG_JSON"])
    raw_config = raw_config_path.read_bytes()
    tools = json.loads(raw_config)
    model_root = Path(tools["models-dir"]["pipeline"]).expanduser().resolve()
    if model_root.parent.name != "snapshots" or len(model_root.name) != 40:
        raise ValueError("MinerU tools config does not select a revision-pinned snapshot")
    trees = provider.get("required_artifact_trees") or {}
    configured = None
    for raw_root, names in trees.items():
        if resolve(root, raw_root).resolve() == model_root:
            configured = names
            break
    if not isinstance(configured, list) or not configured:
        raise ValueError("MinerU snapshot is absent from required_artifact_trees")
    files = {}
    for name in sorted(configured):
        relative = Path(name)
        if not isinstance(name, str) or relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"invalid MinerU model asset path: {name!r}")
        path = model_root / relative
        files[name] = {"sha256": sha256(path), "stat": stat_identity(path)}
    output = resolve(root, provider["model_asset_manifest"])
    write_manifest(output, {
        "schema_version": "1.0", "provider": "mineru_local", "revision": model_root.name,
        "tools_config_sha256": hashlib.sha256(raw_config).hexdigest(), "files": files,
    })
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    root = args.root.expanduser().resolve()
    config = json.loads((root / "configs/providers.json").read_bytes())
    for path in (freeze_indra(root, config), freeze_mineru(root, config)):
        print(f"FROZEN: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
