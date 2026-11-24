"""Production preflight without parsing a PDF, initializing models or downloading."""

from __future__ import annotations

import base64
import importlib.util
import json
import os
import re
import string
import subprocess
import sys
from collections.abc import Mapping
from importlib import metadata
from pathlib import Path
from typing import Any

from pdffast.config import ParserConfig
from pdffast.errors import ConfigurationError
from pdffast.providers.profiles import decode_config_json
from pdffast.providers.workers import worker_environment
from pdffast.providers.base import asset_stat_identity

from .production_identity import SCHEMA_VERSION, build_identity, digest, fingerprint
from .production_profile import ProductionProfile, load_production_profile

ENV_PROBE = """
import importlib.metadata as m, json, platform
print(json.dumps([platform.python_version(), sorted(
    (d.metadata['Name'].lower(), d.version) for d in m.distributions() if d.metadata['Name']
)]))
"""


class RuntimeIdentityError(ValueError):
    """Required model identity is missing or inconsistent with the runtime."""


def _installed_module_versions(distributions: dict[str, str]) -> dict[str, str]:
    versions = {}
    for distribution, module in distributions.items():
        try:
            installed = metadata.distribution(distribution)
        except metadata.PackageNotFoundError as exc:
            raise RuntimeIdentityError(f"{distribution} metadata is missing") from exc
        expected = Path(installed.locate_file(f"{module}/__init__.py")).resolve()
        spec = importlib.util.find_spec(module)
        if spec is None or not spec.origin or Path(spec.origin).resolve() != expected or not expected.is_file():
            raise RuntimeIdentityError(f"{module} would not load from its identified distribution")
        versions[distribution] = installed.version
    return versions


def _packages(
    python: str | None, *, environment: Mapping[str, str],
) -> tuple[str, dict[str, str]]:
    if python is None:
        return sys.version.split()[0], {
            d.metadata["Name"].lower(): d.version for d in metadata.distributions()
            if d.metadata["Name"]
        }
    probe = subprocess.run(
        [python, "-I", "-B", "-c", ENV_PROBE],
        check=True, capture_output=True, text=True, timeout=15, env=environment,
    )
    version, distributions = json.loads(probe.stdout)
    return version, dict(distributions)


def _resolve_paths(snapshot: ProductionProfile, config: dict[str, Any]) -> None:
    registry = snapshot.registry
    if config.get("model_asset_manifest"):
        config["model_asset_manifest"] = str(
            registry._resolve_path(config["model_asset_manifest"], field="model_asset_manifest")
        )
    for key in ("required_artifacts", "required_artifact_manifests"):
        if key in config:
            config[key] = [str(registry._resolve_path(path, field=key)) for path in config[key]]
    for key in ("required_artifact_sha256", "required_artifact_trees"):
        if key in config:
            config[key] = {
                str(registry._resolve_path(path, field=key)): value
                for path, value in config[key].items()
            }
    if "env" in config:
        config["env"] = {
            key: string.Template(value).safe_substitute(snapshot.environment)
            for key, value in config["env"].items()
        }


def _sha256_file(path: Path) -> str:
    from hashlib import sha256

    value = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def _load_asset_manifest(
    config: dict[str, Any],
    *,
    provider: str,
    revision: str,
    root: Path,
    relative_files: list[str],
    verify_hashes: bool,
    tools_config_sha256: str | None = None,
) -> dict[str, Any]:
    raw_path = config.get("model_asset_manifest")
    if not isinstance(raw_path, str) or not Path(raw_path).is_absolute():
        raise RuntimeIdentityError(f"{provider} requires an absolute frozen model asset manifest")
    manifest_path = Path(raw_path)
    raw = manifest_path.read_bytes()
    if manifest_path.stat().st_mode & 0o222:
        raise RuntimeIdentityError(f"{provider} model asset manifest must be read-only")
    data = decode_config_json(raw)
    if (
        data.get("schema_version") != "1.0"
        or data.get("provider") != provider
        or data.get("revision") != revision
        or data.get("tools_config_sha256") != tools_config_sha256
    ):
        raise RuntimeIdentityError(f"{provider} frozen model asset manifest identity mismatch")
    files = data.get("files")
    expected_names = set(relative_files)
    if not isinstance(files, dict) or set(files) != expected_names:
        raise RuntimeIdentityError(f"{provider} frozen model asset manifest file set mismatch")
    hashes: dict[str, str] = {}
    stat_snapshot: dict[str, dict[str, int]] = {}
    for name in sorted(expected_names):
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts or not name:
            raise RuntimeIdentityError(f"{provider} model asset path is invalid: {name!r}")
        record = files[name]
        if not isinstance(record, dict):
            raise RuntimeIdentityError(f"{provider} model asset record is invalid: {name}")
        expected_sha = record.get("sha256")
        expected_stat = record.get("stat")
        if (
            not isinstance(expected_sha, str)
            or not re.fullmatch(r"[0-9a-f]{64}", expected_sha)
            or not isinstance(expected_stat, dict)
        ):
            raise RuntimeIdentityError(f"{provider} model asset digest or stat is invalid: {name}")
        artifact = root / relative
        actual_stat = asset_stat_identity(artifact)
        if actual_stat != expected_stat:
            raise RuntimeIdentityError(f"{provider} model asset changed since freeze: {name}")
        if verify_hashes and _sha256_file(artifact) != expected_sha:
            raise RuntimeIdentityError(f"{provider} model asset SHA-256 mismatch: {name}")
        hashes[name] = expected_sha
        stat_snapshot[str(artifact.resolve())] = actual_stat
    stat_snapshot[str(manifest_path.resolve())] = asset_stat_identity(manifest_path)
    config["_pdffast_asset_stat_snapshot"] = stat_snapshot
    config["_pdffast_asset_manifest_sha256"] = digest(raw)
    return {"asset_manifest_sha256": digest(raw), "asset_files_sha256": hashes}


def _indra(
    config: dict[str, Any], packages: dict[str, str], *, verify_assets: bool = False,
) -> dict[str, Any]:
    model_dir = Path(config["model_dir"])
    manifest = model_dir.parents[1] / "install_manifest.json"
    raw = manifest.read_bytes()
    data = decode_config_json(raw)
    revision = data.get("model_revision_sha")
    if (
        not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}", revision)
        or Path(data["model_dir"]).resolve() != model_dir.resolve()
        or data["package_version"] != packages["indra-ocr"]
    ):
        raise RuntimeIdentityError("Indra install manifest does not match the installed runtime")
    declared = data.get("file_sha256")
    required = {"det.onnx", "rec.onnx", "rec_cjk.onnx", "order.onnx", "meta.json"}
    if config.get("math"):
        required.update({"mathcls.onnx", "math_enc.onnx", "math_dec_init.onnx",
                         "math_dec_step.onnx", "math_meta.json"})
    if not isinstance(declared, dict) or not required <= declared.keys():
        raise RuntimeIdentityError("Indra install manifest lacks required model digests")
    if any(
        Path(name).is_absolute() or ".." in Path(name).parts or not isinstance(value, str)
        or not re.fullmatch(r"[0-9a-f]{64}", value) or not (model_dir / name).is_file()
        for name, value in declared.items()
    ):
        raise RuntimeIdentityError("Indra model declaration or installed model file is invalid")
    installed = {path.name for path in model_dir.iterdir() if path.is_file()}
    if installed - declared.keys():
        raise RuntimeIdentityError("Indra model directory has undeclared files")
    assets = _load_asset_manifest(
        config, provider="indra_local", revision=revision, root=model_dir,
        relative_files=list(declared), verify_hashes=verify_assets,
    )
    return {
        "revision": revision, "manifest_sha256": digest(raw),
        **assets,
        "configuration_files_sha256": {
            name: digest((model_dir / name).read_bytes())
            for name in declared if name.endswith(".json")
        },
        "verification": "FROZEN_SHA256_AND_STAT",
    }


def _rapidocr(config: dict[str, Any], packages: dict[str, str]) -> dict[str, Any]:
    if "rapidocr" not in packages or "onnxruntime" not in packages:
        raise FileNotFoundError("RapidOCR or ONNX Runtime is not installed in the Core interpreter")
    pins = config.get("required_artifact_sha256", {})
    if config.get("config_path") or len(pins) != 3:
        raise RuntimeIdentityError("locked RapidOCR requires exactly three pinned ONNX files")
    options = dict(config.get("params", {}))
    if "${" in json.dumps(options):
        raise RuntimeIdentityError("locked RapidOCR options must be literal values")
    if any(key.endswith((".model_path", ".model_dir", ".engine_type", ".rec_keys_path", ".task_type")) for key in options):
        raise RuntimeIdentityError("locked RapidOCR model or engine override conflicts with pinned files")
    for channel, token in (("Det", "det"), ("Rec", "rec"), ("Cls", "cls")):
        matches = [path for path in pins if f"_{token}_" in Path(path).name and path.endswith(".onnx")]
        if len(matches) != 1:
            raise RuntimeIdentityError(f"RapidOCR requires one pinned {channel} ONNX file")
        options[f"{channel}.model_path"] = matches[0]
    config["params"] = options
    config["locked_onnx"] = True
    _installed_module_versions({"rapidocr": "rapidocr", "onnxruntime": "onnxruntime", "numpy": "numpy"})
    return {"declared_file_sha256": pins, "verification": "SHA256_VERIFIED"}


def _mineru(
    config: dict[str, Any], packages: dict[str, str], *, verify_assets: bool = False,
) -> dict[str, Any]:
    if not {"mineru", "torch", "torchvision"} <= packages.keys():
        raise FileNotFoundError("MinerU, torch or torchvision is missing")
    env = config.get("env", {})
    if set(env) - {
        "PYTHONUNBUFFERED", "MINERU_TOOLS_CONFIG_JSON", "MINERU_MODEL_SOURCE",
        "HF_HOME", "HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "MINERU_DEVICE_MODE",
        "OMP_NUM_THREADS",
    }:
        raise RuntimeIdentityError("unsupported locked MinerU environment override")
    if (
        env.get("MINERU_MODEL_SOURCE") != "local"
        or env.get("HF_HUB_OFFLINE") != "1" or env.get("TRANSFORMERS_OFFLINE") != "1"
        or config.get("backend") != "pipeline"
    ):
        raise RuntimeIdentityError("MinerU requires a local offline pipeline")
    path = Path(env["MINERU_TOOLS_CONFIG_JSON"])
    if not path.is_absolute():
        raise RuntimeIdentityError("MinerU tools config must resolve to an absolute path")
    raw = path.read_bytes()
    data = json.loads(raw)
    root = Path(data["models-dir"]["pipeline"]).expanduser()
    trees = config.get("required_artifact_trees", {})
    if (
        not root.is_absolute() or root.parent.name != "snapshots"
        or not re.fullmatch(r"[0-9a-f]{40}", root.name)
        or str(root) not in trees or not trees[str(root)]
    ):
        raise RuntimeIdentityError("MinerU tools config does not select the declared model snapshot")
    relative_files = trees[str(root)]
    assets = _load_asset_manifest(
        config, provider="mineru_local", revision=root.name, root=root,
        relative_files=relative_files, verify_hashes=verify_assets,
        tools_config_sha256=digest(raw),
    )
    config["_pdffast_mineru_tools_config_b64"] = base64.b64encode(raw).decode("ascii")
    config["_pdffast_mineru_tools_config_sha256"] = digest(raw)
    return {
        "revision": root.name, "tools_config_sha256": digest(raw),
        **assets,
        "configuration_files_sha256": {
            item: digest((root / item).read_bytes())
            for item in relative_files if item.endswith(".json")
        },
        "verification": "FROZEN_SHA256_AND_STAT",
    }


def inspect_runtime(
    snapshot: ProductionProfile, *, probe: bool, verify_assets: bool = False,
) -> dict[str, Any]:
    runtimes = {}
    for name in snapshot.allowed:
        report: dict[str, Any] = {"status": "CHECK_ERROR", "dependency_probe": "NOT_RUN"}
        runtimes[name] = report
        try:
            config = snapshot.configs[name]
            _resolve_paths(snapshot, config)
            prepared = snapshot.registry._prepare_config(config)
            interpreter = prepared.get("python_executable")
            runtime = {"indra_worker": "indra", "mineru_worker": "mineru"}.get(prepared["kind"])
            if runtime is not None:
                if interpreter != str(snapshot.root / f"runtimes/{runtime}/.venv/bin/python"):
                    raise RuntimeIdentityError(f"{runtime} requires its checkout-managed Python environment")
                if not os.access(interpreter, os.X_OK):
                    raise FileNotFoundError("isolated Python executable is missing or not executable")
            elif interpreter is not None:
                raise RuntimeIdentityError("in-process adapters cannot select a separate Python executable")
            if runtime is not None:
                prepared["locked_runtime"] = True
            environment = worker_environment(snapshot.environment)
            environment.update(prepared.get("env", {}))
            version, packages = _packages(interpreter, environment=environment)
            if prepared["kind"] == "indra_worker":
                if "indra-ocr" not in packages:
                    raise FileNotFoundError("indra-ocr is missing")
                model = _indra(prepared, packages, verify_assets=verify_assets)
            elif prepared["kind"] == "rapidocr":
                model = _rapidocr(prepared, packages)
            elif prepared["kind"] == "mineru_worker":
                model = _mineru(prepared, packages, verify_assets=verify_assets)
            else:
                raise RuntimeIdentityError("no strict runtime identity verifier for this adapter")
            if prepared["kind"] == "indra_worker" and prepared.get("env"):
                raise RuntimeIdentityError("locked Indra cannot override its worker environment")
            snapshot.configs[name] = prepared
            report["identity"] = {
                "python": version,
                "package_inventory_sha256": fingerprint(packages),
                "packages": {key: packages[key] for key in (
                    "indra-ocr", "rapidocr", "onnxruntime", "mineru", "torch", "torchvision",
                    "pdfplumber", "pypdfium2", "pdfminer.six", "pillow", "opencv-python", "numpy",
                ) if key in packages},
                "model": model,
            }
            if probe:
                provider = snapshot.registry.create(name, prepared)
                try:
                    available = provider.preflight().available
                    report["dependency_probe"] = "PASS" if available else "FAIL"
                    if not available:
                        report["status"] = "NOT_READY"
                        continue
                finally:
                    provider.close()
            report["status"] = "READY"
        except FileNotFoundError as exc:
            report.update(status="NOT_INSTALLED", error=str(exc))
        except RuntimeIdentityError as exc:
            report.update(status="IDENTITY_UNVERIFIED", error=str(exc))
        except (KeyError, OSError, TypeError, ValueError) as exc:
            report.update(status="MISCONFIGURED", error=str(exc))
        except (RuntimeError, subprocess.SubprocessError) as exc:
            report.update(status="CHECK_ERROR", error=type(exc).__name__)
    return runtimes


def preflight_snapshot(
    snapshot: ProductionProfile, config: ParserConfig, *,
    probe: bool = False, verify_assets: bool = False,
) -> dict[str, Any]:
    runtimes = {}
    try:
        core_dependencies = _installed_module_versions({
            "pdfplumber": "pdfplumber", "pypdfium2": "pypdfium2",
            "pdfminer.six": "pdfminer", "pillow": "PIL",
        })
        runtimes = inspect_runtime(snapshot, probe=probe, verify_assets=verify_assets)
        report = build_identity(snapshot, config, runtimes, core_dependencies)
    except (OSError, TypeError, ValueError, subprocess.SubprocessError) as exc:
        return {
            "schema_version": SCHEMA_VERSION, "status": "PREFLIGHT_FAILED",
            "provider_runtime": runtimes, "error": type(exc).__name__,
        }
    ready = all(runtime["status"] == "READY" for runtime in runtimes.values())
    report.update(
        status="PASS" if ready else "PREFLIGHT_FAILED",
        provider_runtime=runtimes, inference_performed=False,
    )
    if not ready:
        report["effective_config_fingerprint"] = None
    return report


def preflight_production_profile(
    *,
    project_root: Path | str | None = None,
    provider_profile: Path | str | None = None,
    config: ParserConfig | None = None,
    probe: bool = False,
    verify_assets: bool = False,
) -> dict[str, Any]:
    """Return a JSON-compatible V1 report for the same inputs accepted by Core."""
    try:
        if config is not None and (project_root is not None or provider_profile is not None):
            raise ConfigurationError("config cannot be combined with preflight facade options")
        resolved = config if config is not None else ParserConfig(
            project_root=project_root, provider_profile=provider_profile,
        )
        snapshot = load_production_profile(resolved)
    except ConfigurationError as exc:
        return {"schema_version": SCHEMA_VERSION, "status": "CONFIGURATION_FAILED", "error": str(exc)}
    return preflight_snapshot(snapshot, resolved, probe=probe, verify_assets=verify_assets)
