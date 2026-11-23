import json
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from shutil import copyfile

import pytest

from pdffast import ParserConfig, preflight_production_profile
from pdffast.application.production_identity import fingerprint
from pdffast.application.production_profile import load_production_profile

ROOT = Path(__file__).resolve().parents[2]
PROFILE = Path("configs/profiles/production.indra-triple.json")


def test_identity_hashes_used_files_and_only_semantic_options(monkeypatch, tmp_path):
    from pdffast.application import production_preflight as preflight

    monkeypatch.setattr(preflight, "inspect_runtime", lambda snapshot, **kwargs: {
        name: {"status": "READY", "identity": {"revision": "pinned"}}
        for name in snapshot.allowed
    })
    config = ParserConfig(project_root=ROOT, provider_profile=PROFILE)
    result = preflight_production_profile(config=config)
    assert result["status"] == "PASS"
    assert result["profile_sha256"] == sha256((ROOT / PROFILE).read_bytes()).hexdigest()
    assert result["providers_config_sha256"] == sha256((ROOT / "configs/providers.json").read_bytes()).hexdigest()
    assert result["effective_config_fingerprint"] == fingerprint(result["fingerprint_input"])
    from_nonsemantic = preflight_production_profile(config=replace(
        config, output_root=tmp_path, capture_output=False, output_mode="full",
    ))
    from_semantic = preflight_production_profile(config=replace(config, page_dpi=220))
    assert from_nonsemantic["effective_config_fingerprint"] == result["effective_config_fingerprint"]
    assert from_semantic["effective_config_fingerprint"] != result["effective_config_fingerprint"]


def test_routes_providers_models_and_frozen_candidates_change_fingerprint(tmp_path, monkeypatch):
    from pdffast.application import production_preflight

    root = tmp_path / "project"
    provider_path = Path("configs/providers.json")
    frozen_path = Path("configs/frozen/stage9_route_candidates_prod_v001.json")
    for path in (PROFILE, provider_path, frozen_path):
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        copyfile(ROOT / path, root / path)

    revision = "initial"
    monkeypatch.setattr(production_preflight, "inspect_runtime", lambda snapshot, **kwargs: {
        name: {"status": "READY", "identity": {"revision": revision}}
        for name in snapshot.allowed
    })
    config = ParserConfig(project_root=root, provider_profile=PROFILE)

    def current():
        result = preflight_production_profile(config=config)
        assert result["status"] == "PASS"
        return result["effective_config_fingerprint"]

    initial = current()
    monkeypatch.setenv("PDFFAST_LOG_MODE", "debug")
    assert current() == initial
    for path in (PROFILE, provider_path, frozen_path):
        previous = (root / path).read_bytes()
        (root / path).write_bytes(previous + b"\n")
        assert current() != initial
        (root / path).write_bytes(previous)

    profile = json.loads((root / PROFILE).read_bytes())
    profile["chains"]["INLINE_CONTEXT_PARSE"].reverse()
    (root / PROFILE).write_text(json.dumps(profile))
    changed_route = current()
    assert changed_route != initial

    providers = json.loads((root / provider_path).read_bytes())
    providers["providers"]["indra_local"]["threads"] += 1
    (root / provider_path).write_text(json.dumps(providers))
    changed_provider = current()
    assert changed_provider != changed_route

    revision = "updated"
    assert current() != changed_provider


def test_canonical_fingerprint_rejects_non_finite_values():
    with pytest.raises(ValueError):
        fingerprint({"invalid": float("nan")})


def test_indra_rejects_extra_runtime_model_not_in_manifest(tmp_path):
    import json

    from pdffast.application.production_preflight import RuntimeIdentityError, _indra

    root = tmp_path / "indra"
    model = root / "models" / "indra-ocr"
    model.mkdir(parents=True)
    files = ["det.onnx", "rec.onnx", "rec_cjk.onnx", "order.onnx", "meta.json"]
    for name in files + ["rec.int8.onnx"]:
        (model / name).write_bytes(b"fixture")
    (root / "install_manifest.json").write_text(json.dumps({
        "model_revision_sha": "a" * 40, "model_dir": str(model), "package_version": "1.1.2",
        "file_sha256": {name: "b" * 64 for name in files},
    }))
    with pytest.raises(RuntimeIdentityError, match="undeclared"):
        _indra({"model_dir": str(model)}, {"indra-ocr": "1.1.2"})


def test_rapidocr_rejects_interpolated_options():
    from pdffast.application.production_preflight import RuntimeIdentityError, _rapidocr

    config = {
        "required_artifact_sha256": {f"fake_{name}_test.onnx": "a" * 64 for name in ("det", "rec", "cls")},
        "params": {"Global.text_score": "${oc.env:SCORE}"},
    }
    with pytest.raises(RuntimeIdentityError, match="literal"):
        _rapidocr(config, {"rapidocr": "x", "onnxruntime": "x"})


def test_preflight_failure_for_missing_profile(tmp_path):
    result = preflight_production_profile(
        project_root=tmp_path, provider_profile="missing.json",
    )
    assert result["status"] == "CONFIGURATION_FAILED"
    invalid = preflight_production_profile(project_root=tmp_path, provider_profile="bad\x00profile")
    assert invalid["status"] == "CONFIGURATION_FAILED"


def test_locked_profile_keeps_file_snapshot(tmp_path):
    path = tmp_path / "profile.json"
    profile_bytes = (ROOT / PROFILE).read_bytes()
    path.write_bytes(profile_bytes)
    snapshot = load_production_profile(ParserConfig(project_root=ROOT, provider_profile=path))
    path.write_text("{}")
    assert snapshot.profile_bytes == profile_bytes
    assert snapshot.chains["PAGE_DOCUMENT_LAYOUT_PARSE"] == ["mineru_local"]


def test_locked_snapshot_keeps_effective_environment(monkeypatch, tmp_path):
    from pdffast.application.production_identity import build_identity
    from pdffast.providers.workers import JsonLineWorker

    monkeypatch.setenv("MINERU_DEVICE_MODE", "cpu")
    monkeypatch.setenv("LD_LIBRARY_PATH", "/pinned/library")
    monkeypatch.setenv("PDFFAST_REVIEW_MODEL_ROOT", str(tmp_path / "pinned"))
    config = ParserConfig(project_root=ROOT, provider_profile=PROFILE)
    snapshot = load_production_profile(config)
    runtimes = {name: {"identity": {}} for name in snapshot.allowed}
    identity = build_identity(snapshot, config, runtimes, {})

    monkeypatch.setenv("MINERU_DEVICE_MODE", "cuda")
    monkeypatch.setenv("LD_LIBRARY_PATH", "/different/library")
    monkeypatch.setenv("PDFFAST_REVIEW_MODEL_ROOT", str(tmp_path / "changed"))
    assert build_identity(snapshot, config, runtimes, {}) == identity
    assert snapshot.registry._resolve_path(
        "${PDFFAST_REVIEW_MODEL_ROOT}/models", field="test",
    ) == tmp_path / "pinned" / "models"

    value = str(tmp_path / "${MINERU_DEVICE_MODE}" / "mineru.json")
    worker = JsonLineWorker(
        python_executable=Path("python"), worker_code="", dependency_probe_code="",
        env={"MINERU_TOOLS_CONFIG_JSON": value}, locked_runtime=True,
        environment=snapshot.environment,
    )
    assert worker._env()["MINERU_DEVICE_MODE"] == "cpu"
    assert worker._env()["LD_LIBRARY_PATH"] == "/pinned/library"
    assert worker._env()["MINERU_TOOLS_CONFIG_JSON"] == value


def test_code_identity_ignores_ambient_git_repository(monkeypatch):
    from pdffast.application.production_identity import code_identity

    identity = code_identity()
    for key in ("GIT_DIR", "GIT_COMMON_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        monkeypatch.setenv(key, "/nonexistent-other-git-context")
    assert code_identity() == identity


@pytest.mark.parametrize("phase", ["before_native", "during_native"])
def test_locked_parse_rejects_in_process_environment_drift(tmp_path, monkeypatch, phase):
    from test_native_only_provider_plan import native_pdf

    from pdffast import ParseExecutionError, PDFFastParser
    from pdffast.application import production_preflight
    from pdffast.pipeline import runner

    monkeypatch.setenv("ORT_LOG_SEVERITY_LEVEL", "2")

    def ready(snapshot, **kwargs):
        if phase == "before_native":
            monkeypatch.setenv("ORT_LOG_SEVERITY_LEVEL", "3")
        return {name: {"status": "READY", "identity": {}} for name in snapshot.allowed}

    monkeypatch.setattr(production_preflight, "inspect_runtime", ready)
    profile = runner.run_profiler

    def changed_profile(**kwargs):
        if phase == "during_native":
            monkeypatch.setenv("ORT_LOG_SEVERITY_LEVEL", "3")
        return profile(**kwargs)

    monkeypatch.setattr(runner, "run_profiler", changed_profile)
    pdf = tmp_path / "native.pdf"
    pdf.write_bytes(native_pdf())
    parser = PDFFastParser(project_root=ROOT, provider_profile=PROFILE, output_root=tmp_path)
    with pytest.raises(ParseExecutionError, match="semantic environment changed"):
        parser.parse(pdf, run_id="drift")
    assert not (tmp_path / "drift/result/manifest.json").exists()


def test_clean_release_commit_changes_fingerprint_even_with_same_source(monkeypatch):
    from pdffast.application import production_identity

    config = ParserConfig(project_root=ROOT, provider_profile=PROFILE)
    snapshot = load_production_profile(config)
    code = {
        "pdffast_commit": "a" * 40,
        "source_dirty": True,
        "source_sha256": "b" * 64,
        "algorithm_sha256": {"native": "c" * 64},
    }
    monkeypatch.setattr(production_identity, "code_identity", lambda: dict(code))
    runtimes = {name: {"identity": {}} for name in snapshot.allowed}
    candidate = production_identity.build_identity(snapshot, config, runtimes, {})

    code["source_dirty"] = False
    clean_same_commit = production_identity.build_identity(snapshot, config, runtimes, {})
    assert clean_same_commit["effective_config_fingerprint"] == candidate["effective_config_fingerprint"]

    code["pdffast_commit"] = "d" * 40
    release = production_identity.build_identity(snapshot, config, runtimes, {})
    assert release["pdffast_commit"] == release["code_identity"]["pdffast_commit"] == "d" * 40
    assert release["code_identity"]["source_sha256"] == candidate["code_identity"]["source_sha256"]
    assert release["effective_config_fingerprint"] != candidate["effective_config_fingerprint"]


def test_locked_parse_allows_opencv_loader_to_change_subprocess_library_path(tmp_path, monkeypatch):
    import os

    from test_native_only_provider_plan import native_pdf

    from pdffast import PDFFastParser
    from pdffast.application import production_preflight
    from pdffast.pipeline import runner

    monkeypatch.setattr(production_preflight, "inspect_runtime", lambda snapshot, **kwargs: {
        name: {"status": "READY", "identity": {}} for name in snapshot.allowed
    })
    profile = runner.run_profiler

    def with_opencv_loader(**kwargs):
        monkeypatch.setenv("LD_LIBRARY_PATH", "/opencv/library:" + os.environ.get("LD_LIBRARY_PATH", ""))
        return profile(**kwargs)

    monkeypatch.setattr(runner, "run_profiler", with_opencv_loader)
    pdf = tmp_path / "native.pdf"
    pdf.write_bytes(native_pdf())
    parser = PDFFastParser(project_root=ROOT, provider_profile=PROFILE, output_root=tmp_path)
    assert parser.parse(pdf, run_id="opencv-init").parser_provenance["execution_status"] == "COMPLETED"
