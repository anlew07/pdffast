"""Native-complete PDFs need no provider work, but malformed plans still fail."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from pdffast.fallback import planner, policy, router
from pdffast.fallback.executor import execute_provider_plan
from pdffast.quality.gate import QualityReport

CANDIDATES = (
    Path(__file__).resolve().parents[2]
    / "configs/frozen/stage9_route_candidates_prod_v001.json"
)


def native_plan(tmp_path):
    quality = QualityReport(
        {
            "stage": 8,
            "artifact_role": "page_and_region_quality_gate_and_routing_plan",
            "quality_gate_completed": True,
            "fallback_executed": False,
            "source_file": "native.pdf",
            "page_count": 2,
            "summary": {"document_status": "NATIVE_COMPLETE"},
            "pages": [
                {
                    "page_number": page,
                    "gate_state": "HARD_PASS",
                    "decision": "NATIVE_PASS",
                }
                for page in (1, 2)
            ],
        }
    )
    fallback = planner.create_fallback_plan(
        quality_report=quality,
        quality_gate_path=tmp_path / "quality_gate.json",
        pdf_path=tmp_path / "native.pdf",
        output_dir=tmp_path / "fallback",
        render_inputs=False,
    )
    assert fallback.data["tasks"] == []
    return router.create_capability_plan(
        fallback_plan=fallback, manifest_path=tmp_path / "fallback.json"
    )


class NoProviders:
    def create(self, *_args, **_kwargs):
        raise AssertionError("Native-complete documents must not instantiate providers")


def no_normalization(*_args):
    raise AssertionError("No OCR output exists to normalize")


def test_native_complete_plan_flows_through_execution_without_fake_tasks(tmp_path):
    capability = native_plan(tmp_path)
    plan = policy.create_provider_execution_plan(capability, CANDIDATES)
    assert plan.data["tasks"] == []
    assert plan.data["summary"]["task_count"] == 0
    result = execute_provider_plan(
        execution_plan=plan,
        provider_configs={},
        registry=NoProviders(),
        normalizer=no_normalization,
        output_dir=tmp_path / "executed",
    )
    assert result.manifest["summary"]["task_count"] == 0
    assert result.manifest["summary"]["selected_artifact_count"] == 0
    assert result.manifest["batch_history"] == []
    assert result.selected_predictions == []
    assert not (tmp_path / "executed/selected_predictions").exists()


@pytest.mark.parametrize(
    "mutation",
    [
        "tasks_missing",
        "tasks_null",
        "tasks_object",
        "summary_missing",
        "task_count_nonzero",
        "routed_nonzero",
        "unrouted_nonzero",
        "bound_nonzero",
        "unbound_nonzero",
        "duplicate_nonzero",
        "route_counts_nonempty",
        "type_counts_nonempty",
        "page_count_missing",
        "page_count_zero",
        "task_count_bool",
        "wrong_status",
        "wrong_version",
    ],
)
def test_empty_plan_still_rejects_missing_or_contradictory_data(tmp_path, mutation):
    plan = deepcopy(native_plan(tmp_path).data)
    if mutation == "tasks_missing":
        plan.pop("tasks")
    elif mutation == "tasks_null":
        plan["tasks"] = None
    elif mutation == "tasks_object":
        plan["tasks"] = {}
    elif mutation == "summary_missing":
        plan.pop("summary")
    elif mutation == "task_count_nonzero":
        plan["summary"]["task_count"] = 1
    elif mutation == "routed_nonzero":
        plan["summary"]["routed_task_count"] = 1
    elif mutation == "unrouted_nonzero":
        plan["summary"]["unrouted_task_count"] = 1
    elif mutation == "bound_nonzero":
        plan["summary"]["provider_bound_count"] = 1
    elif mutation == "unbound_nonzero":
        plan["summary"]["provider_unbound_count"] = 1
    elif mutation == "duplicate_nonzero":
        plan["summary"]["duplicate_task_id_count"] = 1
    elif mutation == "route_counts_nonempty":
        plan["summary"]["capability_route_counts"] = {"PAGE_DOCUMENT_OCR": 1}
    elif mutation == "type_counts_nonempty":
        plan["summary"]["task_type_counts"] = {"PAGE_FALLBACK": 1}
    elif mutation == "page_count_missing":
        plan.pop("page_count")
    elif mutation == "page_count_zero":
        plan["page_count"] = 0
    elif mutation == "task_count_bool":
        plan["summary"]["task_count"] = False
    elif mutation == "wrong_status":
        plan["status"] = "UNKNOWN"
    elif mutation == "wrong_version":
        plan["version"] = "unknown"
    with pytest.raises(ValueError):
        policy.create_provider_execution_plan(router.CapabilityPlan(plan), CANDIDATES)


def native_pdf() -> bytes:
    """A genuine two-page native-text PDF; no external rendering dependency."""
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R 4 0 R] /Count 2 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 5 0 R >> >> /Contents 6 0 R >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 5 0 R >> >> /Contents 7 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    for page in (1, 2):
        lines = [f"Native research proposal page {page}"] + [
            f"Experiment {page}-{i} examines sensor sampling and edge reliability under load."
            for i in range(12)
        ]
        stream = (
            b"BT /F1 10 Tf 45 780 Td 30 TL "
            + b" T* ".join(b"(" + line.encode() + b") Tj" for line in lines)
            + b" ET"
        )
        objects.append(
            b"<< /Length "
            + str(len(stream)).encode()
            + b" >>\nstream\n"
            + stream
            + b"\nendstream"
        )
    pdf = b"%PDF-1.4\n"
    offsets = []
    for number, obj in enumerate(objects, 1):
        offsets.append(len(pdf))
        pdf += f"{number} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(pdf)
    pdf += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    pdf += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    return (
        pdf
        + f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    )


def test_real_http_parse_native_pdf_exports_native_text_and_json(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from pdffast import PDFFastParser
    from pdffast.service import app as service

    monkeypatch.setattr(
        service,
        "create_parser",
        lambda: PDFFastParser(
            output_root=tmp_path,
            output_mode="full",
            provider_configs={},
            registry=NoProviders(),
            normalizer=no_normalization,
        ),
    )
    with TestClient(service.app) as client:
        response = client.post(
            "/parse", files={"file": ("native.pdf", native_pdf(), "application/pdf")}
        )
    assert response.status_code == 200, response.text
    data = response.json()
    assert "sensor sampling" in data["markdown"]
    run = tmp_path / data["run_id"]
    quality = json.loads((run / "08_stage8/quality_gate.json").read_text())
    assert quality["summary"]["document_status"] == "NATIVE_COMPLETE"
    assert quality["page_count"] == 2
    assert (run / "result/document.md").read_text() == data["markdown"]
    assert json.loads((run / "result/document.json").read_text()) == data["canonical"]
    execution = json.loads(
        (
            run / "09_8_production_fallback/production_execution_manifest.json"
        ).read_text()
    )
    assert execution["summary"]["task_count"] == 0


def test_native_complete_does_not_bypass_route_configuration_validation(tmp_path):
    capability = native_plan(tmp_path)
    candidates = tmp_path / "invalid-candidates.json"
    candidates.write_text(
        json.dumps({"stage": 9, "substage": "9.6.2", "version": "0.1.0", "routes": {}})
    )
    with pytest.raises(ValueError, match="missing route"):
        policy.create_provider_execution_plan(capability, candidates)
