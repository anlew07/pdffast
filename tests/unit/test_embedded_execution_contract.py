import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator, ValidationError

from pdffast.application.execution_contract import build_execution_contract
from pdffast.pipeline.artifacts import ArtifactPaths


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "docs/contracts/embedded_execution.v1.schema.json"
SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
VALIDATOR = Draft202012Validator(SCHEMA)

SHA256 = "a" * 64
COMMIT = "b" * 40
PROVIDERS = ("indra_local", "rapidocr_ch_light", "mineru_local")


def _artifact(name: str, path: str, media_type: str = "application/json") -> dict:
    return {
        "name": name,
        "path": path,
        "media_type": media_type,
        "byte_size": 128,
        "sha256": SHA256,
    }


def _contract() -> dict:
    return {
        "schema_version": "pdffast.execution.v1",
        "run_id": "contract-test-run",
        "input": {
            "algorithm": "sha256",
            "sha256": SHA256,
            "byte_size": 4096,
            "status": "COMPLETE",
        },
        "result": {
            "document": "result/document.json",
            "markdown": "result/document.md",
            "audit": "result/audit.json",
        },
        "execution": {
            "execution_status": "COMPLETED",
            "pdffast_commit": COMMIT,
            "source_sha256": SHA256,
            "profile_name": "production.indra-triple",
            "profile_sha256": SHA256,
            "providers_config_sha256": SHA256,
            "effective_config_fingerprint": SHA256,
            "policy_version": "9.6.3",
            "allowed_providers": list(PROVIDERS),
            "provider_runtime": {
                name: {
                    "status": "READY",
                    "dependency_probe": "PASS",
                    "identity": {
                        "python": "3.12.13",
                        "package_inventory_sha256": SHA256,
                        "packages": {"example": "1.2.3"},
                        "model": {"revision": "test-revision"},
                    },
                }
                for name in PROVIDERS
            },
            "attempted_provider_counts": {},
            "selected_provider_counts": {},
            "planned_task_count": 0,
            "accepted_task_count": 0,
            "terminal_preserve_count": 0,
            "pipeline_failure_count": 0,
            "escalated_count": 0,
            "preflight_status": "PASS",
            "audit_passed": True,
            "outputs_written": True,
        },
        "execution_evidence": {
            "production_manifest": (
                "09_8_production_fallback/production_execution_manifest.json"
            ),
            "selected_prediction_index": (
                "09_8_production_fallback/selected_prediction_index.json"
            ),
            "runtime_policy": (
                "09_6_3_runtime_policy/runtime_escalation_policy.json"
            ),
        },
        "artifacts": [
            _artifact("document", "result/document.json"),
            _artifact("markdown", "result/document.md", "text/markdown"),
            _artifact("audit", "result/audit.json"),
            _artifact(
                "production_execution_manifest",
                "09_8_production_fallback/production_execution_manifest.json",
            ),
            _artifact(
                "selected_prediction_index",
                "09_8_production_fallback/selected_prediction_index.json",
            ),
            _artifact(
                "runtime_escalation_policy",
                "09_6_3_runtime_policy/runtime_escalation_policy.json",
            ),
        ],
    }


def test_embedded_execution_schema_is_valid() -> None:
    Draft202012Validator.check_schema(SCHEMA)


def test_native_only_execution_contract_is_valid() -> None:
    contract = _contract()

    VALIDATOR.validate(contract)

    assert contract["execution"]["planned_task_count"] == 0
    assert contract["execution"]["attempted_provider_counts"] == {}
    assert contract["execution"]["selected_provider_counts"] == {}


def test_partial_pipeline_failure_is_preserved_not_flattened() -> None:
    contract = _contract()
    execution = contract["execution"]
    execution.update(
        execution_status="COMPLETED_WITH_PIPELINE_FAILURES",
        attempted_provider_counts={"indra_local": 2, "rapidocr_ch_light": 1},
        selected_provider_counts={"rapidocr_ch_light": 1},
        planned_task_count=2,
        accepted_task_count=1,
        terminal_preserve_count=0,
        pipeline_failure_count=1,
        escalated_count=1,
    )

    VALIDATOR.validate(contract)
    assert execution["execution_status"] == "COMPLETED_WITH_PIPELINE_FAILURES"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda data: data.update(schema_version="pdffast.execution.v2"),
        lambda data: data.update(run_id="../escape"),
        lambda data: data["input"].update(sha256="not-a-digest"),
        lambda data: data["result"].update(document="/tmp/document.json"),
        lambda data: data["execution_evidence"].update(
            runtime_policy="../outside/runtime.json"
        ),
        lambda data: data["artifacts"][0].update(sha256="short"),
        lambda data: data["artifacts"].pop(),
    ],
)
def test_execution_contract_rejects_invalid_identity_and_artifacts(mutate) -> None:
    contract = copy.deepcopy(_contract())
    mutate(contract)

    with pytest.raises(ValidationError):
        VALIDATOR.validate(contract)


def test_selected_prediction_artifact_requires_task_id() -> None:
    contract = _contract()
    contract["artifacts"].append(
        _artifact(
            "selected_prediction",
            "09_8_production_fallback/selected_predictions/task-1.json",
        )
    )

    with pytest.raises(ValidationError):
        VALIDATOR.validate(contract)

    contract["artifacts"][-1]["task_id"] = "task-1"
    VALIDATOR.validate(contract)


def test_completed_contract_cannot_contain_pipeline_failures() -> None:
    contract = _contract()
    contract["execution"]["pipeline_failure_count"] = 1

    with pytest.raises(ValidationError):
        VALIDATOR.validate(contract)


def test_partial_contract_requires_positive_pipeline_failure_count() -> None:
    contract = _contract()
    contract["execution"]["execution_status"] = "COMPLETED_WITH_PIPELINE_FAILURES"

    with pytest.raises(ValidationError):
        VALIDATOR.validate(contract)


def test_execution_contract_builder_hashes_required_and_task_evidence(tmp_path) -> None:
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    paths = ArtifactPaths.for_run(run_dir)
    input_bytes = b"%PDF-1.7\\nexecution-contract-fixture\\n"
    input_pdf = tmp_path / "input.pdf"
    input_pdf.write_bytes(input_bytes)
    input_metadata = {
        "algorithm": "sha256",
        "sha256": hashlib.sha256(input_bytes).hexdigest(),
        "byte_size": len(input_bytes),
        "status": "COMPLETE",
    }
    payloads = {
        paths.result.document_json: b'{"page_count": 1}',
        paths.result.document_md: b"# Parsed document\n",
        paths.result.audit_json: b'{"validation": {"pass": true}}',
        paths.providers.production_manifest: b'{"summary": {"escalated_count": 1}}',
        paths.providers.selected_index: b'{"items": []}',
        paths.observability.execution_plan: b'{"version": "9.6.3"}',
        paths.providers.selected_dir / "task-1.json": b'{"attempts": []}',
    }
    for path, payload in payloads.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)

    context = SimpleNamespace(
        run_id="run-1",
        run_dir=run_dir,
        pdf=input_pdf,
        artifacts=paths,
        input_metadata=input_metadata,
    )
    identity = {
        "status": "PASS",
        "pdffast_commit": COMMIT,
        "code_identity": {"source_sha256": SHA256},
        "profile_name": "production.indra-triple",
        "profile_sha256": SHA256,
        "providers_config_sha256": SHA256,
        "effective_config_fingerprint": SHA256,
        "allowed_providers": list(PROVIDERS),
        "provider_runtime": {
            name: {
                "status": "READY",
                "dependency_probe": "PASS",
                "identity": {
                    "python": "3.12.13",
                    "package_inventory_sha256": SHA256,
                    "packages": {"example": "1.2.3"},
                    "model": {"revision": "test-revision"},
                },
            }
            for name in PROVIDERS
        },
    }
    statistics = {
        "execution_status": "COMPLETED_WITH_PIPELINE_FAILURES",
        "attempted_provider_counts": {"indra_local": 2, "rapidocr_ch_light": 1},
        "selected_provider_counts": {"rapidocr_ch_light": 1},
        "planned_task_count": 2,
        "accepted_task_count": 1,
        "terminal_preserve_count": 0,
        "pipeline_failure_count": 1,
    }
    execution_plan = SimpleNamespace(data={"version": "9.6.3"})
    production_manifest = {"summary": {"escalated_count": 1}}

    contract = build_execution_contract(
        context,
        production_identity=identity,
        statistics=statistics,
        execution_plan=execution_plan,
        production_manifest=production_manifest,
    )

    VALIDATOR.validate(contract)
    assert contract["run_id"] == "run-1"
    assert contract["execution"]["execution_status"] == "COMPLETED_WITH_PIPELINE_FAILURES"
    assert contract["execution"]["provider_runtime"]["indra_local"]["identity"]["model"]["revision"] == "test-revision"
    by_path = {item["path"]: item for item in contract["artifacts"]}
    selected_path = "09_8_production_fallback/selected_predictions/task-1.json"
    assert by_path[selected_path]["task_id"] == "task-1"
    assert by_path[selected_path]["sha256"] == hashlib.sha256(payloads[paths.providers.selected_dir / "task-1.json"]).hexdigest()
    assert contract["execution_evidence"]["production_manifest"] in by_path
    assert "result/manifest.json" not in by_path

    input_pdf.write_bytes(b"%PDF-1.7\\nmutated-after-parse\\n")
    with pytest.raises(ValueError, match="input PDF changed"):
        build_execution_contract(
            context,
            production_identity=identity,
            statistics=statistics,
            execution_plan=execution_plan,
            production_manifest=production_manifest,
        )


def test_execution_contract_builder_rejects_artifact_symlink_escape(tmp_path) -> None:
    run_dir = tmp_path / "run-2"
    run_dir.mkdir()
    paths = ArtifactPaths.for_run(run_dir)
    input_bytes = b"%PDF-1.7\\nsymlink-fixture\\n"
    input_pdf = tmp_path / "input.pdf"
    input_pdf.write_bytes(input_bytes)
    input_metadata = {
        "algorithm": "sha256",
        "sha256": hashlib.sha256(input_bytes).hexdigest(),
        "byte_size": len(input_bytes),
        "status": "COMPLETE",
    }
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    paths.result.document_json.parent.mkdir(parents=True, exist_ok=True)
    paths.result.document_json.symlink_to(outside)
    for path in (
        paths.result.document_md,
        paths.result.audit_json,
        paths.providers.production_manifest,
        paths.providers.selected_index,
        paths.observability.execution_plan,
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")

    context = SimpleNamespace(
        run_id="run-2",
        run_dir=run_dir,
        pdf=input_pdf,
        artifacts=paths,
        input_metadata=input_metadata,
    )
    identity = {
        "status": "PASS",
        "pdffast_commit": COMMIT,
        "code_identity": {"source_sha256": SHA256},
        "profile_name": "production.indra-triple",
        "profile_sha256": SHA256,
        "providers_config_sha256": SHA256,
        "effective_config_fingerprint": SHA256,
        "allowed_providers": list(PROVIDERS),
        "provider_runtime": {
            name: {"status": "READY", "identity": {}}
            for name in PROVIDERS
        },
    }
    statistics = {
        "execution_status": "COMPLETED",
        "attempted_provider_counts": {},
        "selected_provider_counts": {},
        "planned_task_count": 0,
        "accepted_task_count": 0,
        "terminal_preserve_count": 0,
        "pipeline_failure_count": 0,
    }

    with pytest.raises(ValueError, match="symlink"):
        build_execution_contract(
            context,
            production_identity=identity,
            statistics=statistics,
            execution_plan=SimpleNamespace(data={"version": "9.6.3"}),
            production_manifest={"summary": {"escalated_count": 0}},
        )


def test_execution_contract_matches_real_provider_execution_evidence(tmp_path) -> None:
    from test_fallback_executor import FakeProvider, FakeRegistry, _canonical, _task

    from pdffast.application.parser_provenance import collect_execution_statistics
    from pdffast.fallback.executor import execute_provider_plan
    from pdffast.fallback.policy import ProviderExecutionPlan

    run_dir = tmp_path / "provider-run"
    run_dir.mkdir()
    paths = ArtifactPaths.for_run(run_dir)
    input_bytes = b"%PDF-1.7\\nprovider-execution-fixture\\n"
    input_pdf = tmp_path / "provider-input.pdf"
    input_pdf.write_bytes(input_bytes)
    input_metadata = {
        "algorithm": "sha256",
        "sha256": hashlib.sha256(input_bytes).hexdigest(),
        "byte_size": len(input_bytes),
        "status": "COMPLETE",
    }

    first, second = "rapidocr_ch_light", "mineru_local"
    task = _task("provider-fallback", [first, second])
    plan = ProviderExecutionPlan({
        "version": "0.1.2",
        "source_file": input_pdf.name,
        "tasks": [task],
        "summary": {"task_count": 1},
    })
    first_provider = FakeProvider(first, {"provider-fallback": RuntimeError("retry me")})
    second_provider = FakeProvider(
        second,
        {"provider-fallback": _canonical("provider-fallback", second, "recovered text")},
    )
    execution = execute_provider_plan(
        execution_plan=plan,
        provider_configs={
            first: {"kind": "rapidocr", "runtime_enabled": True},
            second: {"kind": "mineru_worker", "runtime_enabled": True},
        },
        registry=FakeRegistry({first: first_provider, second: second_provider}),
        normalizer=lambda raw, metadata, **kwargs: raw.payload,
        output_dir=paths.providers.execution_dir,
        locked_routes={"REGION_MULTIMODAL_PARSE": [first, second]},
    )
    paths.observability.execution_plan.parent.mkdir(parents=True, exist_ok=True)
    paths.observability.execution_plan.write_text(
        json.dumps(plan.data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    for path, payload in (
        (paths.result.document_json, b'{"page_count": 1}'),
        (paths.result.document_md, b"# Parsed document\\n"),
        (paths.result.audit_json, b'{"validation": {"pass": true}}'),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)

    statistics = collect_execution_statistics(
        plan,
        execution,
        (first, second),
        output_dir=paths.providers.execution_dir,
        plan_path=paths.observability.execution_plan,
    )
    identity = {
        "status": "PASS",
        "pdffast_commit": COMMIT,
        "code_identity": {"source_sha256": SHA256},
        "profile_name": "production.test-profile",
        "profile_sha256": SHA256,
        "providers_config_sha256": SHA256,
        "effective_config_fingerprint": SHA256,
        "allowed_providers": [first, second],
        "provider_runtime": {
            name: {
                "status": "READY",
                "dependency_probe": "NOT_RUN",
                "identity": {
                    "python": "3.12.13",
                    "package_inventory_sha256": SHA256,
                    "packages": {"example": "1.2.3"},
                    "model": {"revision": "fixture"},
                },
            }
            for name in (first, second)
        },
    }
    context = SimpleNamespace(
        run_id="provider-run",
        run_dir=run_dir,
        pdf=input_pdf,
        artifacts=paths,
        input_metadata=input_metadata,
    )

    contract = build_execution_contract(
        context,
        production_identity=identity,
        statistics=statistics,
        execution_plan=plan,
        production_manifest=execution.manifest,
    )

    VALIDATOR.validate(contract)
    assert statistics["attempted_provider_counts"] == {first: 1, second: 1}
    assert statistics["selected_provider_counts"] == {second: 1}
    assert contract["execution"]["escalated_count"] == 1
    selected = next(
        item for item in contract["artifacts"]
        if item["name"] == "selected_prediction"
    )
    assert selected["task_id"] == "provider-fallback"
    assert selected["path"].endswith("selected_predictions/provider-fallback.json")
    assert selected["sha256"] == hashlib.sha256(
        paths.providers.selected_prediction("provider-fallback").read_bytes()
    ).hexdigest()
