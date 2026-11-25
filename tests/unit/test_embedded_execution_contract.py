import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError


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
