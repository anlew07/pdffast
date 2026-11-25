import hashlib
import json
from pathlib import Path

import pytest

from pdffast import ConfigurationError, PDFFastParser
from pdffast.fallback.executor import execute_provider_plan
from pdffast.fallback.policy import ProviderExecutionPlan

ROOT = Path(__file__).resolve().parents[2]
PROFILE = ROOT / "configs/profiles/production.indra-triple.json"


@pytest.mark.parametrize("versioned", [False, True])
def test_locked_native_only_manifest_and_exclusive_run(tmp_path, monkeypatch, versioned):
    from test_native_only_provider_plan import native_pdf

    from pdffast.application import production_preflight

    rapidocr_pins = {
        str(tmp_path / f"models/{channel}.onnx"): "a" * 64
        for channel in ("det", "rec", "cls")
    }

    def inspect_runtime(snapshot, **kwargs):
        return {
            name: {
                "status": "READY",
                "dependency_probe": "NOT_RUN",
                "identity": {
                    "python": "3.12.13",
                    "package_inventory_sha256": "a" * 64,
                    "packages": {"test-package": "1.0"},
                    "model": (
                        {"declared_file_sha256": rapidocr_pins, "verification": "SHA256_VERIFIED"}
                        if name == "rapidocr_ch_light" else {"revision": "test-fixture"}
                    ),
                },
            }
            for name in snapshot.allowed
        }

    monkeypatch.setattr(production_preflight, "inspect_runtime", inspect_runtime)
    pdf = tmp_path / "native.pdf"
    pdf.write_bytes(native_pdf())
    parser = PDFFastParser(project_root=ROOT, provider_profile=PROFILE, output_root=tmp_path)
    request = {
        "schema_version": "pdffast.execution.request.v1",
        "run_id": "locked",
        "input": {"sha256": hashlib.sha256(pdf.read_bytes()).hexdigest()},
        "options": {},
    }
    if versioned:
        result = parser.parse_request(pdf, request)
    else:
        result = parser.parse(pdf, run_id="locked")
    manifest = result.artifacts["result_manifest"]
    manifest_data = json.loads(manifest.read_bytes())
    provenance = manifest_data["parser_provenance"]
    contract = manifest_data["execution_contract"]
    from scripts.verify_production_governance import _execution_contract_validator

    _execution_contract_validator().validate(contract)
    assert contract["status"] == "SUCCESS"
    assert contract["error"] is None
    assert contract["result"]["manifest"] == "result/manifest.json"
    rapidocr_model = contract["execution"]["provider_runtime"]["rapidocr_ch_light"]["identity"]["model"]
    assert rapidocr_model["declared_file_sha256"] == {
        Path(path).name: digest for path, digest in rapidocr_pins.items()
    }
    assert str(tmp_path) not in json.dumps(contract)
    assert all(Path(path).is_absolute() for path in rapidocr_pins)
    if versioned:
        assert contract["request"] == request
        assert contract["input"]["sha256"] == request["input"]["sha256"]
        assert "EXPECTED_INPUT_SHA256_NOT_SUPPLIED" not in contract["risk_flags"]
    else:
        assert "request" not in contract
        assert "EXPECTED_INPUT_SHA256_NOT_SUPPLIED" in contract["risk_flags"]
    assert "PROVIDER_DEPENDENCY_PROBE_NOT_RUN" in contract["risk_flags"]
    assert "INPUT_NOT_SNAPSHOTTED" not in contract["risk_flags"]
    assert result.parser_provenance == provenance
    assert result.execution_contract == contract
    assert result["execution_contract"] == contract
    assert contract["run_id"] == "locked"
    assert contract["execution"]["execution_status"] == "COMPLETED"
    assert contract["execution"]["planned_task_count"] == 0
    assert contract["execution"]["attempted_provider_counts"] == {}
    assert contract["execution"]["selected_provider_counts"] == {}
    assert contract["input"]["sha256"] == manifest_data["input"]["sha256"]
    assert result.artifacts["production_execution_manifest"].is_file()
    assert result.artifacts["selected_prediction_index"].is_file()
    assert result.artifacts["runtime_escalation_policy"].is_file()
    assert provenance["execution_status"] == "COMPLETED"
    assert provenance["planned_task_count"] == 0
    assert provenance["attempted_provider_counts"] == {}
    assert provenance["selected_provider_counts"] == {}
    assert provenance["provider_execution_required"] is False
    assert provenance["audit_passed"] is True
    assert result["production_manifest"]["summary"]["task_count"] == 0
    first_manifest = manifest.read_bytes()
    with pytest.raises(ConfigurationError, match="run directory"):
        parser.parse(pdf, run_id="locked")
    assert manifest.read_bytes() == first_manifest
    default_parser = PDFFastParser(output_root=tmp_path)
    with pytest.raises(ConfigurationError, match="locked run directory"):
        default_parser.parse(pdf, run_id="locked")
    assert manifest.read_bytes() == first_manifest

    from scripts.verify_production_governance import summarize_parse

    expected = {"status": "PASS", **provenance, "provider_runtime": inspect_runtime(
        production_preflight.load_production_profile(parser._resolved_config()),
    )}
    input_sha256 = json.loads(first_manifest)["input"]["sha256"]
    import subprocess
    import sys

    code = """
import os, resource, signal, sys
from pathlib import Path
resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
manifest = Path(sys.argv[1])
manifest.write_bytes(manifest.read_bytes())
if sys.argv[2] == "-6":
    os.kill(os.getpid(), signal.SIGABRT)
raise SystemExit(int(sys.argv[2]))
"""
    for returncode in (7, -6):
        child = subprocess.run([sys.executable, "-c", code, str(manifest), str(returncode)], check=False)
        assert child.returncode == returncode
        summary = summarize_parse(manifest.parents[1], child.returncode, expected, input_sha256=input_sha256)
        assert summary["manifest_written"] is True
        assert summary["acceptance"] == "FAIL"
    assert summarize_parse(manifest.parents[1], 0, expected, input_sha256=input_sha256)["acceptance"] == "PASS"
    if versioned:
        tampered = json.loads(first_manifest)
        tampered["execution_contract"]["request"]["input"]["sha256"] = "0" * 64
        manifest.write_text(json.dumps(tampered))
        summary = summarize_parse(manifest.parents[1], 0, expected, input_sha256=input_sha256)
        assert summary["execution_contract_verified"] is False
        manifest.write_bytes(first_manifest)

    # Independently hash all delivered artifacts and reject per-file tampering.
    for descriptor in contract["artifacts"]:
        path = manifest.parents[1] / descriptor["path"]
        payload = path.read_bytes()
        assert descriptor["sha256"] == hashlib.sha256(payload).hexdigest()
        assert descriptor["byte_size"] == len(payload)
        path.write_bytes(payload + b" ")
        try:
            tampered_report = summarize_parse(
                manifest.parents[1], 0, expected, input_sha256=input_sha256,
            )
            assert tampered_report["acceptance"] == "FAIL", descriptor["name"]
            assert tampered_report["execution_contract_verified"] is False
        finally:
            path.write_bytes(payload)

    # It also rejects unsafe run-relative paths in the published contract.
    tampered = json.loads(first_manifest)
    tampered["execution_contract"]["artifacts"][0]["path"] = "../outside.json"
    manifest.write_text(json.dumps(tampered))
    tampered_report = summarize_parse(
        manifest.parents[1], 0, expected, input_sha256=input_sha256,
    )
    assert tampered_report["acceptance"] == "FAIL"
    assert tampered_report["execution_contract_verified"] is False
    manifest.write_bytes(first_manifest)

    # The external release verifier must join execution evidence to this input
    # and run even when the child reported a normal exit.
    for mutate in (
        lambda data: data.update(run_id="different-run"),
        lambda data: data["input"].update(sha256="0" * 64),
        lambda data: data["parser_provenance"].update(selected_provider_counts={"unexpected": 1}),
    ):
        tampered = json.loads(first_manifest)
        mutate(tampered)
        manifest.write_text(json.dumps(tampered))
        assert summarize_parse(manifest.parents[1], 0, expected, input_sha256=input_sha256)["acceptance"] == "FAIL"


def test_input_mutation_during_parse_prevents_final_manifest(tmp_path, monkeypatch):
    from test_native_only_provider_plan import native_pdf

    from pdffast import ParseExecutionError
    from pdffast.application import production_preflight
    from pdffast.pipeline import runner

    monkeypatch.setattr(production_preflight, "inspect_runtime", lambda snapshot, **kwargs: {
        name: {
            "status": "READY",
            "dependency_probe": "NOT_RUN",
            "identity": {
                "python": "3.12.13",
                "package_inventory_sha256": "a" * 64,
                "packages": {"test-package": "1.0"},
                "model": {"revision": "test-fixture"},
            },
        }
        for name in snapshot.allowed
    })
    source = tmp_path / "mutable.pdf"
    source.write_bytes(native_pdf())
    original_run_stage10 = runner.run_stage10

    def run_stage10_then_mutate(*args, **kwargs):
        result = original_run_stage10(*args, **kwargs)
        source.write_bytes(source.read_bytes() + b"\\nmutated-after-stage10\\n")
        return result

    monkeypatch.setattr(runner, "run_stage10", run_stage10_then_mutate)
    parser = PDFFastParser(project_root=ROOT, provider_profile=PROFILE, output_root=tmp_path)

    with pytest.raises(ParseExecutionError, match="input PDF changed"):
        parser.parse(source, run_id="input-mutation")

    assert not (tmp_path / "input-mutation" / "result" / "manifest.json").exists()


def test_cancellation_at_final_publication_keeps_manifest_absent(tmp_path):
    from threading import Event

    from pdffast.application.parser_provenance import publish_manifest
    from pdffast.runtime import ParseCancelledError, cancellable_parse

    cancelled = Event()
    cancelled.set()
    path = tmp_path / "manifest.json"
    with cancellable_parse(cancelled), pytest.raises(ParseCancelledError):
        publish_manifest(path, {"execution_status": "COMPLETED"})
    assert not path.exists()
    assert not list(tmp_path.iterdir())


def test_audit_fault_leaves_no_final_locked_manifest(tmp_path, monkeypatch):
    from test_native_only_provider_plan import native_pdf

    from pdffast import OutputValidationError
    from pdffast.application import production_preflight

    monkeypatch.setattr(production_preflight, "inspect_runtime", lambda snapshot, **kwargs: {
        name: {
            "status": "READY",
            "dependency_probe": "NOT_RUN",
            "identity": {
                "python": "3.12.13",
                "package_inventory_sha256": "a" * 64,
                "packages": {"test-package": "1.0"},
                "model": {"revision": "test-fixture"},
            },
        }
        for name in snapshot.allowed
    })
    monkeypatch.setattr("pdffast.pipeline.runner.audit", lambda *args, **kwargs: {"validation": {"pass": False}})
    source = tmp_path / "native.pdf"
    source.write_bytes(native_pdf())
    parser = PDFFastParser(project_root=ROOT, provider_profile=PROFILE, output_root=tmp_path)
    with pytest.raises(OutputValidationError) as error:
        parser.parse(source, run_id="audit-fault")
    assert error.value.status == "OUTPUT_VALIDATION_FAILED"
    result = tmp_path / "audit-fault" / "result"
    assert (result / "document.md").is_file()
    assert not (result / "manifest.json").exists()


def test_provenance_counts_dispatch_fallback_terminal_and_unresolved(tmp_path):
    from test_fallback_executor import FakeProvider, FakeRegistry, _canonical, _task

    from pdffast.application.parser_provenance import collect_execution_statistics

    first, second = "rapidocr_ch_light", "mineru_local"
    chain = [first, second]
    tasks = [_task("recovered", chain), _task("preserved", chain, terminal=True),
             _task("unresolved", chain)]
    plan = ProviderExecutionPlan({"tasks": tasks, "summary": {"task_count": len(tasks)}})
    first_provider = FakeProvider(first, {task["task_id"]: RuntimeError("fault injection") for task in tasks})
    second_provider = FakeProvider(second, {
        task["task_id"]: _canonical(
            task["task_id"], second, "recovered" if task["task_id"] == "recovered" else "",
        ) for task in tasks
    })
    run = execute_provider_plan(
        execution_plan=plan, registry=FakeRegistry({first: first_provider, second: second_provider}),
        provider_configs={
            first: {"kind": "rapidocr", "runtime_enabled": True},
            second: {"kind": "mineru_worker", "runtime_enabled": True},
        },
        normalizer=lambda result, task, **kwargs: result.payload,
        output_dir=tmp_path, locked_routes={"REGION_MULTIMODAL_PARSE": chain},
    )
    plan_path = tmp_path / "runtime_escalation_policy.json"
    plan_path.write_text(json.dumps(plan.data), encoding="utf-8")
    stats = collect_execution_statistics(
        plan, run, (first, second), output_dir=tmp_path, plan_path=plan_path,
    )
    assert stats["attempted_provider_counts"] == {first: 3, second: 3}
    assert stats["selected_provider_counts"] == {second: 1}
    assert stats["accepted_task_count"] == stats["pipeline_failure_count"] == stats["terminal_preserve_count"] == 1
    assert stats["execution_status"] == "COMPLETED_WITH_PIPELINE_FAILURES"
    selected_file = tmp_path / "selected_predictions" / f"{tasks[0]['task_id']}.json"
    saved_selected = json.loads(selected_file.read_text(encoding="utf-8"))
    saved_selected["selected_provider"] = first
    selected_file.write_text(json.dumps(saved_selected), encoding="utf-8")
    with pytest.raises(ValueError, match="persisted selected prediction"):
        collect_execution_statistics(
            plan, run, (first, second), output_dir=tmp_path, plan_path=plan_path,
        )
    selected_file.write_text(json.dumps(run.selected_predictions[0]), encoding="utf-8")
    plan_path.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="persisted runtime escalation policy"):
        collect_execution_statistics(
            plan, run, (first, second), output_dir=tmp_path, plan_path=plan_path,
        )
    plan_path.write_text(json.dumps(plan.data), encoding="utf-8")
    run.selected_predictions[0]["selected_provider"] = first
    with pytest.raises(ValueError, match="differs from index"):
        collect_execution_statistics(plan, run, (first, second))


@pytest.mark.parametrize("channel", ["manifest", "index", "missing_prediction"])
def test_reject_contradictory_zero_task_records(tmp_path, channel):
    from pdffast.application.parser_provenance import collect_execution_statistics

    plan = ProviderExecutionPlan({"tasks": [], "summary": {"task_count": 0}})
    result = execute_provider_plan(
        execution_plan=plan, provider_configs={}, registry=object(),
        normalizer=lambda *args, **kwargs: {}, output_dir=tmp_path,
    )
    if channel == "manifest":
        result.manifest["summary"]["attempt_provider_counts"] = {"unexpected": 1}
    elif channel == "index":
        result.selected_index["task_count"] = 1
    else:
        result.selected_predictions.append({"task_id": "other"})
    with pytest.raises(ValueError):
        collect_execution_statistics(plan, result, ())


@pytest.fixture
def embedded_parse(tmp_path, monkeypatch):
    from test_native_only_provider_plan import native_pdf

    from pdffast.application import production_preflight

    monkeypatch.setattr(production_preflight, "inspect_runtime", lambda snapshot, **kwargs: {
        name: {
            "status": "READY",
            "dependency_probe": "NOT_RUN",
            "identity": {
                "python": "3.12.13",
                "package_inventory_sha256": "a" * 64,
                "packages": {"test-package": "1.0"},
                "model": {"revision": "test-fixture"},
            },
        }
        for name in snapshot.allowed
    })
    source = tmp_path / "native.pdf"
    source.write_bytes(native_pdf())
    request = {
        "schema_version": "pdffast.execution.request.v1",
        "run_id": "embedded-error",
        "input": {"sha256": hashlib.sha256(source.read_bytes()).hexdigest()},
        "options": {},
    }
    return PDFFastParser(
        project_root=ROOT, provider_profile=PROFILE, output_root=tmp_path / "runs",
    ), source, request


def assert_failure(error, request, code, status, stage):
    from jsonschema import Draft202012Validator

    response = error.to_contract()
    schema = json.loads((ROOT / "docs/contracts/embedded_execution_error.v1.schema.json").read_bytes())
    Draft202012Validator(schema).validate(response)
    assert response["run_id"] == request["run_id"]
    assert response["status"] == status
    assert response["error"]["code"] == code
    assert response["error"]["stage"] == stage
    assert response["error"]["retryable"] is False
    return response


def test_embedded_production_preflight_reports_only_safe_details(embedded_parse, monkeypatch):
    from pdffast import ProductionPreflightError
    from pdffast.application import parse_service

    parser, source, request = embedded_parse
    monkeypatch.setattr(parse_service, "preflight_snapshot", lambda *args: {
        "status": "PREFLIGHT_FAILED",
        "error": "/Users/private/token=PRIVATE",
        "provider_runtime": {"indra_local": {"status": "NOT_INSTALLED", "error": "PRIVATE"}},
    })
    with pytest.raises(ProductionPreflightError) as exc:
        parser.parse_request(source, request)
    response = assert_failure(
        exc.value, request, "PRODUCTION_PREFLIGHT_FAILED", "BLOCKED", "production_preflight",
    )
    assert response["error"]["details"] == {"provider_status": {"indra_local": "NOT_INSTALLED"}}
    assert "PRIVATE" not in json.dumps(response)
    assert not parser.output_root.exists()


@pytest.mark.parametrize("failure", ["initialize", "execute", "cleanup"])
def test_embedded_provider_failure_retains_runtime_evidence(embedded_parse, monkeypatch, failure):
    from test_fallback_executor import FakeProvider, _task

    from pdffast import ParseExecutionError
    from pdffast.pipeline import runner
    from pdffast.providers.registry import ProviderRegistry

    parser, source, request = embedded_parse
    chain = ["indra_local", "rapidocr_ch_light", "mineru_local"]
    task = _task("provider-task", chain)
    create_plan = runner.create_provider_execution_plan

    def plan_with_failure(*args, **kwargs):
        plan = create_plan(*args, **kwargs)
        plan.data["tasks"] = [task]
        plan.data["summary"]["task_count"] = 1
        return plan

    monkeypatch.setattr(runner, "create_provider_execution_plan", plan_with_failure)

    class FailingProvider(FakeProvider):
        def initialize(self):
            if failure == "initialize":
                raise RuntimeError("/Users/private/test-token")
            super().initialize()

        def close(self):
            if failure == "cleanup" and self.name == "indra_local":
                raise RuntimeError("/Users/private/test-token")
            super().close()

    monkeypatch.setattr(ProviderRegistry, "create", lambda self, name, config: FailingProvider(
        name, {"provider-task": RuntimeError("/Users/private/test-token")},
    ))
    with pytest.raises(ParseExecutionError) as exc:
        parser.parse_request(source, request)
    if failure == "initialize":
        response = assert_failure(
            exc.value, request, "PROVIDER_INITIALIZATION_FAILED", "FAILED", "provider_initialization",
        )
        assert response["error"]["details"] == {
            "provider": "indra_local", "task_ids": ["provider-task"],
            "initialization_started": True, "initialization_succeeded": False,
            "cause_type": "RuntimeError",
        }
    elif failure == "cleanup":
        response = assert_failure(
            exc.value, request, "PARSE_EXECUTION_FAILED", "FAILED", "provider_cleanup",
        )
        assert response["error"]["details"] == {"provider": "indra_local", "cause_type": "RuntimeError"}
    else:
        response = assert_failure(
            exc.value, request, "PROVIDER_EXECUTION_FAILED", "FAILED", "provider_execution",
        )
        assert response["error"]["details"]["pipeline_failure_count"] == 1
        assert response["error"]["details"]["task_ids"] == ["provider-task"]
    assert "test-token" not in json.dumps(response)
    assert not (parser.output_root / request["run_id"] / "result/manifest.json").exists()


def test_embedded_audit_and_cooperative_cancel(embedded_parse, monkeypatch):
    from threading import Event

    from pdffast import OutputValidationError
    from pdffast.runtime import ParseCancelledError, cancellable_parse

    parser, source, request = embedded_parse
    monkeypatch.setattr("pdffast.pipeline.runner.audit", lambda *args, **kw: {"validation": {"pass": False}})
    with pytest.raises(OutputValidationError) as exc:
        parser.parse_request(source, request)
    assert_failure(exc.value, request, "OUTPUT_VALIDATION_FAILED", "FAILED", "output_validation")
    assert not (parser.output_root / request["run_id"] / "result/manifest.json").exists()

    request = {**request, "run_id": "cancelled"}
    cancelled = Event()
    cancelled.set()
    with cancellable_parse(cancelled), pytest.raises(ParseCancelledError) as exc:
        parser.parse_request(source, request)
    assert_failure(exc.value, request, "PARSE_CANCELLED", "CANCELLED", "runtime_cancellation")
    assert not (parser.output_root / request["run_id"]).exists()


@pytest.mark.parametrize(("terminal", "has_content", "heading_only", "render_pass"), [
    (True, True, False, True),
    (True, False, False, True),
    (False, False, False, True),
    (False, False, True, True),
    (False, True, False, False),
])
def test_embedded_publication_requires_usable_output_and_renderer_validation(
    embedded_parse, monkeypatch, v3_pipeline_inputs, terminal, has_content, heading_only, render_pass,
):
    from test_fallback_executor import FakeProvider, _task

    from pdffast import OutputValidationError
    from pdffast.fallback.router import CapabilityPlan
    from pdffast.native.text_flow import TextFlowResult
    from pdffast.pipeline import runner
    from pdffast.providers.registry import ProviderRegistry
    from pdffast.quality.gate import QualityReport
    from scripts.verify_production_governance import _execution_contract_validator

    parser, source, request = embedded_parse
    inputs = v3_pipeline_inputs
    native = inputs["native_flow"]
    quality = inputs["quality_gate"]
    capability = inputs["capability_plan"]
    for item in (native, quality, capability):
        item["source_file"] = source.name
    if not has_content:
        native["records"][0]["text"] = ""
        if not heading_only:
            native["sections"][0]["section_title"] = None
    if not terminal:
        quality["pages"][0]["non_text_assessment"]["regions"][0]["action"] = "PRESERVE_VISUAL"
    metadata = capability["tasks"][0]
    task_id = metadata["task_id"]
    task = {
        **_task(task_id, ["indra_local", "rapidocr_ch_light", "mineru_local"], terminal=True),
        **metadata,
    }
    create_plan = runner.create_provider_execution_plan
    run_stage10 = runner.run_stage10
    render = runner.build_rendered_document
    if not terminal:
        capability["tasks"] = []

    def terminal_plan(*args, **kwargs):
        plan = create_plan(*args, **kwargs)
        plan.data["tasks"] = [task] if terminal else []
        plan.data["summary"]["task_count"] = int(terminal)
        return plan

    def render_fixture(context, *, selection, **kwargs):
        return run_stage10(
            context, selection=selection,
            text_flow=TextFlowResult({}, {}, {}, {}, native),
            quality_report=QualityReport(quality),
            capability_plan=CapabilityPlan(capability),
        )

    def renderer_with_invalid_report(document):
        markdown, report = render(document)
        report["validation"]["pass"] = False
        return markdown, report

    if not render_pass:
        monkeypatch.setattr(runner, "build_rendered_document", renderer_with_invalid_report)
    monkeypatch.setattr(runner, "create_provider_execution_plan", terminal_plan)
    monkeypatch.setattr(runner, "run_stage10", render_fixture)
    monkeypatch.setattr(runner, "resolve_document_units_from_artifacts", lambda *a, **kw: ((), ()))
    monkeypatch.setattr(ProviderRegistry, "create", lambda self, name, config: FakeProvider(
        name, {task_id: RuntimeError("fixture provider could not recover the region")},
    ))
    if render_pass and (has_content or heading_only):
        result = parser.parse_request(source, request)
        contract = result.execution_contract
        _execution_contract_validator().validate(contract)
        assert contract["status"] == ("PARTIAL_SUCCESS" if terminal else "SUCCESS")
        assert contract["execution"]["pipeline_failure_count"] == 0
        assert contract["execution"]["terminal_preserve_count"] == int(terminal)
        assert ("TERMINAL_PRESERVATION_PRESENT" in contract["risk_flags"]) is terminal
        assert result.audit["validation"]["pass"] is True
        assert ("V3 原生正文" if has_content else "一、原生内容") in result.markdown
        assert result.artifacts["result_manifest"].is_file()
    else:
        with pytest.raises(OutputValidationError) as exc:
            parser.parse_request(source, request)
        code = "NO_USABLE_RESULT" if render_pass else "OUTPUT_VALIDATION_FAILED"
        assert_failure(exc.value, request, code, "FAILED", "output_validation")
        assert not (parser.output_root / request["run_id"] / "result/manifest.json").exists()


def test_embedded_facade_config_failure_preserves_run_id(embedded_parse):
    _, source, request = embedded_parse
    parser = PDFFastParser(output_mode="invalid", provider_profile=PROFILE)
    with pytest.raises(ConfigurationError) as exc:
        parser.parse_request(source, request)
    assert_failure(
        exc.value, request, "INVALID_CONFIGURATION_OR_REQUEST", "BLOCKED", "request_validation",
    )
