import json
from pathlib import Path

import pytest

from pdffast import ConfigurationError, PDFFastParser
from pdffast.fallback.executor import execute_provider_plan
from pdffast.fallback.policy import ProviderExecutionPlan

ROOT = Path(__file__).resolve().parents[2]
PROFILE = ROOT / "configs/profiles/production.indra-triple.json"


def test_locked_native_only_manifest_and_exclusive_run(tmp_path, monkeypatch):
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
    pdf = tmp_path / "native.pdf"
    pdf.write_bytes(native_pdf())
    parser = PDFFastParser(project_root=ROOT, provider_profile=PROFILE, output_root=tmp_path)
    result = parser.parse(pdf, run_id="locked")
    manifest = result.artifacts["result_manifest"]
    manifest_data = json.loads(manifest.read_bytes())
    provenance = manifest_data["parser_provenance"]
    contract = manifest_data["execution_contract"]
    schema = json.loads(
        (ROOT / "docs/contracts/embedded_execution.v1.schema.json").read_text(encoding="utf-8")
    )
    import jsonschema

    jsonschema.validate(contract, schema)
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

    expected = {"status": "PASS", **provenance}
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
