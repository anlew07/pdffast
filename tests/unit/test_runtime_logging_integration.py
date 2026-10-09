"""Observe production orchestration without starting heavyweight providers."""

import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from pdffast.application.parse_service import ParseService
from pdffast.config import ParserConfig
from pdffast.errors import ConfigurationError, ParseExecutionError
from pdffast.fallback.executor import execute_provider_plan, ProviderExecutionResult
from pdffast.fallback.policy import ProviderExecutionPlan
from pdffast.fallback.router import CapabilityPlan
from pdffast.native.text_flow import TextFlowResult
from pdffast.pipeline import runner
from pdffast.pipeline.context import PipelineContext
from pdffast.providers.base import ProviderPreflight, RawProviderResult
from pdffast.quality.evidence import EvidenceReport
from pdffast.quality.gate import QualityReport
from pdffast.result import ParseResult
from pdffast import runtime


@pytest.fixture
def events():
    records = []
    class Collector(logging.Handler):
        def emit(self, record): records.append(record)
    collector = Collector()
    logger = logging.getLogger("pdffast.runtime.events")
    logger.addHandler(collector)
    yield records
    logger.removeHandler(collector)


def context(tmp_path, run_id="pipeline"):
    return PipelineContext.create(
        project_root=tmp_path, pdf=tmp_path / "input.pdf", output_root=tmp_path,
        run_id=run_id, case_id=None, page_dpi=200, region_dpi=300,
        rapidocr_workers=1, table_mode="auto",
    )


def stub_calculation(monkeypatch):
    """Replace expensive algorithms, keeping orchestration/output/event code real."""
    values = {
        "run_profiler": {}, "run_section_discovery": {}, "run_page_structure": {},
        "run_table_recovery": {}, "create_text_flow_result": TextFlowResult({}, {}, {}, {}, {}),
        "create_evidence_report": EvidenceReport({}), "evaluate_evidence_report": QualityReport({}),
        "create_fallback_plan": None, "create_capability_plan": CapabilityPlan({}),
        "create_provider_execution_plan": ProviderExecutionPlan({"tasks": []}),
        "execute_provider_plan": ProviderExecutionResult({}, {"items": []}, []),
        "resolve_document_units_from_artifacts": ((), ()),
        "build_document": {"records": []}, "build_rendered_document": ("# actual", {}),
        "audit": {"validation": {"pass": True}},
    }
    for name, value in values.items():
        monkeypatch.setattr(runner, name, lambda *args, value=value, **kwargs: value)
    for name in (
        "write_text_flow_result", "write_evidence_report", "write_quality_report",
        "write_fallback_plan", "write_capability_plan", "write_provider_execution_plan",
    ):
        monkeypatch.setattr(runner, name, lambda *args, **kwargs: None)


def test_real_runner_emits_semantic_events_and_preserves_result(tmp_path, monkeypatch, events):
    stub_calculation(monkeypatch)
    result = runner.run_core_pipeline(context(tmp_path), execute_providers=True,
        provider_configs={}, registry=object(), normalizer=object())
    assert isinstance(result, ParseResult) and result.markdown == "# actual"
    expected = ["parse_started", "native_analysis_started", "native_analysis_finished",
        "quality_completed", "fallback_planning_completed", "provider_execution_started",
        "canonical_completed", "renderer_completed", "audit_completed", "parse_finished"]
    emitted = [r.event for r in events]
    assert [event for event in emitted if event in expected] == expected
    assert all(r.run_id == "pipeline" for r in events)
    assert json.loads((tmp_path / "pipeline/result/audit.json").read_text()) == {"validation": {"pass": True}}


def test_profiler_failure_logs_phase_original_exception_and_traceback(tmp_path, monkeypatch, events):
    def fail(**kwargs): raise ValueError("invalid PDF")
    monkeypatch.setattr(runner, "run_profiler", fail)
    with pytest.raises(ParseExecutionError, match="invalid PDF"):
        runner.run_core_pipeline(context(tmp_path, "failed"))
    failure = next(r for r in events if r.event == "parse_failed")
    assert failure.run_id == "failed"
    assert failure.current_phase == "native_observation"
    assert failure.exception_type == "ValueError"
    assert failure.exception_message == "invalid PDF"
    assert "Traceback" in (tmp_path / "failed/diagnostics/logs/pipeline.log").read_text()


def test_configuration_failure_is_observed_before_runner(tmp_path, events):
    with pytest.raises(ConfigurationError):
        ParseService(ParserConfig(project_root=tmp_path, output_root=tmp_path)).parse(
            tmp_path / "input.pdf", run_id="config-failure")
    assert [r.event for r in events] == ["parse_started", "parse_failed"]
    assert events[-1].exception_type == "ConfigurationError"


def task(task_id, chain, terminal=False):
    result = {"task_id": task_id, "capability_route": "PAGE_DOCUMENT_OCR",
        "input_image": "input.png", "provider_chain": [{"provider": p} for p in chain],
        "output_contract": {"required": ["text"], "empty_text_requires_warning": True}}
    if terminal: result["terminal_fallback"] = {"action": "PRESERVE_SOURCE_REGION_UNRESOLVED"}
    return result


class Provider:
    def __init__(self, name, fails=False, heartbeat=None):
        self.name, self.fails, self.heartbeat = name, fails, heartbeat
        self.closed = False
    def preflight(self): return ProviderPreflight(self.name, True)
    def initialize(self): pass
    def execute(self, task):
        if self.heartbeat is not None:
            assert self.heartbeat.wait(2), "provider ran without heartbeat"
        if self.fails: raise RuntimeError("provider unavailable during execution")
        return RawProviderResult(self.name, task.task_id, "SUCCESS", {
            "status": "SUCCESS", "text": {"availability": "AVAILABLE", "content": "recovered"}})
    def close(self): self.closed = True


def test_provider_attempts_heartbeat_and_completed_counts_are_real(tmp_path, events):
    ready = threading.Event()
    class Heartbeat(logging.Handler):
        def emit(self, record):
            if getattr(record, "event", None) == "parse_heartbeat" and getattr(record, "task_id", None):
                ready.set()
    logger = logging.getLogger("pdffast.runtime.events")
    handler = Heartbeat()
    logger.addHandler(handler)
    p1, p2 = Provider("rapidocr_ch_light", fails=True, heartbeat=ready), Provider("mineru_local")
    class Registry:
        def create(self, name, config): return {p1.name: p1, p2.name: p2}[name]
    tasks = [task("escalate", [p1.name, p2.name]), task("terminal", [p1.name], True)]
    try:
        with runtime.observe_parse("providers", heartbeat_interval=0.01):
            result = execute_provider_plan(execution_plan=ProviderExecutionPlan({"tasks": tasks}),
                provider_configs={p1.name: {"kind": "rapidocr", "runtime_enabled": True},
                    p2.name: {"kind": "mineru_worker", "runtime_enabled": True}},
                registry=Registry(), normalizer=lambda raw, task, **kwargs: raw.payload, output_dir=tmp_path)
    finally:
        logger.removeHandler(handler)
    heartbeat = next(r for r in events if r.event == "parse_heartbeat" and getattr(r, "task_id", None))
    assert heartbeat.provider == p1.name and heartbeat.task_id == "escalate"
    assert heartbeat.task_elapsed_seconds > 0
    assert heartbeat.completed_tasks == 0 and heartbeat.total_tasks == 2
    finished = [r for r in events if r.event == "provider_task_finished"]
    assert [(r.task_id, r.accepted, r.completed_tasks) for r in finished] == [
        ("escalate", False, 0), ("terminal", False, 0), ("escalate", True, 2)]
    failure = next(r for r in events if r.event == "provider_task_failed")
    assert failure.provider == p1.name and failure.task_id == "escalate"
    assert failure.exception_type == "RuntimeError" and failure.exc_info
    assert result.manifest["summary"]["terminal_preserve_count"] == 1
    assert p1.closed and p2.closed


def test_http_v1_response_and_concurrent_request_run_ids(tmp_path, monkeypatch, events):
    pytest.importorskip("fastapi", reason="HTTP adapter needs the service extra")
    from fastapi.testclient import TestClient
    from pdffast.service import app as service
    from pdffast.parser import PDFFastParser
    barrier = threading.Barrier(2)
    stub_calculation(monkeypatch)
    def profiler(**kwargs):
        barrier.wait(timeout=2)
        return {}
    monkeypatch.setattr(runner, "run_profiler", profiler)
    monkeypatch.setattr(service, "create_parser", lambda: PDFFastParser(config=ParserConfig(
        project_root=tmp_path, output_root=tmp_path,
        provider_configs={}, registry=object(), normalizer=object(),
    )))
    with TestClient(service.app) as client:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: client.post("/parse", files={"file": ("input.pdf", b"%PDF-test", "application/pdf")}), range(2)))
    run_ids = set()
    for response in results:
        assert response.status_code == 200
        payload = response.json()
        assert set(payload) == {"schema_version", "run_id", "markdown", "canonical", "audit"}
        assert payload["schema_version"] == "1.0" and payload["markdown"] == "# actual"
        run_ids.add(payload["run_id"])
    assert len(run_ids) == 2
    assert {r.run_id for r in events if r.event == "parse_started"} == run_ids
    assert {r.run_id for r in events if r.event == "parse_finished"} == run_ids
    for run_id in run_ids:
        log = (tmp_path / run_id / "diagnostics/logs/pipeline.log").read_text()
        assert "canonical_completed" in log and "audit_completed" in log
        other = next(item for item in run_ids if item != run_id)
        assert other not in log
