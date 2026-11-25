import base64
import hashlib
import json
from pathlib import Path

import pytest

from pdffast.application.production_preflight import RuntimeIdentityError, _mineru
from pdffast.providers.base import (
    ProviderAssetIntegrityError, asset_stat_identity, validate_asset_stat_snapshot,
)
from pdffast.providers.mineru import MinerUProvider


def _write_asset_manifest(path: Path, *, root: Path, config_raw: bytes, data: bytes) -> None:
    asset = root / "models" / "weights.safetensors"
    manifest = {
        "schema_version": "1.0",
        "provider": "mineru_local",
        "revision": root.name,
        "tools_config_sha256": hashlib.sha256(config_raw).hexdigest(),
        "files": {
            "models/weights.safetensors": {
                "sha256": hashlib.sha256(data).hexdigest(),
                "stat": asset_stat_identity(asset),
            }
        },
    }
    path.write_text(json.dumps(manifest), encoding="utf-8")
    path.chmod(0o444)


def _mineru_config(tmp_path: Path):
    root = tmp_path / "models--test" / "snapshots" / ("a" * 40)
    asset = root / "models" / "weights.safetensors"
    asset.parent.mkdir(parents=True)
    payload = b"frozen model bytes"
    asset.write_bytes(payload)
    tools = tmp_path / "mineru.json"
    raw = json.dumps({"models-dir": {"pipeline": str(root)}}).encode()
    tools.write_bytes(raw)
    manifest = tmp_path / "model_assets_manifest.json"
    _write_asset_manifest(manifest, root=root, config_raw=raw, data=payload)
    config = {
        "kind": "mineru_worker",
        "runtime_enabled": True,
        "backend": "pipeline",
        "model_asset_manifest": str(manifest),
        "required_artifact_trees": {str(root): ["models/weights.safetensors"]},
        "env": {
            "MINERU_TOOLS_CONFIG_JSON": str(tools),
            "MINERU_MODEL_SOURCE": "local",
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
        },
    }
    return config, tools, raw, asset, payload


def test_mineru_preflight_binds_config_bytes_and_model_assets(tmp_path):
    config, tools, raw, asset, payload = _mineru_config(tmp_path)
    identity = _mineru(config, {"mineru": "3.4.5", "torch": "2.5", "torchvision": "0.20"})
    assert identity["verification"] == "FROZEN_SHA256_AND_STAT"
    assert identity["asset_files_sha256"]["models/weights.safetensors"] == hashlib.sha256(payload).hexdigest()
    assert base64.b64decode(config["_pdffast_mineru_tools_config_b64"]) == raw
    validate_asset_stat_snapshot(config)

    tools.write_text('{"models-dir":{"pipeline":"/different/snapshot"}}', encoding="utf-8")
    assert base64.b64decode(config["_pdffast_mineru_tools_config_b64"]) == raw

    asset.write_bytes(b"changed model bytes")
    with pytest.raises(ProviderAssetIntegrityError, match="changed after preflight"):
        validate_asset_stat_snapshot(config)


def test_mineru_worker_uses_private_preflight_config_snapshot(tmp_path):
    import sys

    original = tmp_path / "mineru.json"
    payload = b'{"models-dir":{"pipeline":"/frozen/snapshot"}}'
    original.write_bytes(payload)
    provider = MinerUProvider("mineru_local", {
        "kind": "mineru_worker",
        "runtime_enabled": True,
        "locked_runtime": True,
        "python_executable": str(Path(sys.executable)),
        "env": {"MINERU_TOOLS_CONFIG_JSON": str(original)},
        "_pdffast_mineru_tools_config_b64": base64.b64encode(payload).decode("ascii"),
        "_pdffast_mineru_tools_config_sha256": hashlib.sha256(payload).hexdigest(),
    })
    worker = provider._default_worker_factory(provider.config)
    snapshot_path = Path(worker.extra_env["MINERU_TOOLS_CONFIG_JSON"])
    assert snapshot_path.read_bytes() == payload
    original.write_text('{"models-dir":{"pipeline":"/changed"}}', encoding="utf-8")
    assert snapshot_path.read_bytes() == payload
    provider.close()
    assert not snapshot_path.exists()


def test_mineru_asset_hash_verification_rejects_mismatched_frozen_sha(tmp_path):
    config, _, raw, asset, payload = _mineru_config(tmp_path)
    asset.write_bytes(b"different bytes")
    manifest_path = Path(config["model_asset_manifest"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"]["models/weights.safetensors"]["stat"] = asset_stat_identity(asset)
    manifest_path.chmod(0o644)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    manifest_path.chmod(0o444)
    with pytest.raises(RuntimeIdentityError, match="SHA-256 mismatch"):
        _mineru(
            config, {"mineru": "3.4.5", "torch": "2.5", "torchvision": "0.20"},
            verify_assets=True,
        )
