from pathlib import Path

from pdffast.quality import gate
from pdffast.fallback import planner, router


def test_stage_objects_flow_without_intermediate_json_and_match_wrappers(
    tmp_path: Path, monkeypatch
) -> None:
    manifest_path = tmp_path / "evidence.json"
    manifest_path.write_text("{}", encoding="utf-8")
    pdf_path = tmp_path / "input.pdf"
    pdf_path.touch()
    quality_dir = tmp_path / "quality"
    fallback_dir = tmp_path / "fallback"
    routing_dir = tmp_path / "routing"
    quality_data = {
        "stage": 8,
        "artifact_role": "page_and_region_quality_gate_and_routing_plan",
        "quality_gate_completed": True,
        "fallback_executed": False,
        "source_file": "input.pdf",
        "page_count": 1,
        "version": "0.3.2",
        "quality_gate_schema_version": "1.4",
        "summary": {},
        "pages": [{
            "page_number": 1,
            "gate_state": "HARD_FALLBACK",
            "decision": "OCR_REQUIRED",
            "route": "PAGE_OCR",
            "reason": "scan",
            "observations": {},
            "non_text_assessment": {},
        }],
    }
    monkeypatch.setattr(gate, "build_quality_gate", lambda *args: quality_data)

    def fake_render(pdf, tasks, out, page_dpi, region_dpi):
        tasks[0]["input_image"] = str(out / "inputs/page/p0001_page.png")

    monkeypatch.setattr(planner, "render_task_inputs", fake_render)

    quality = gate.create_quality_report(
        manifest_path=manifest_path, pdf_path=pdf_path, output_dir=quality_dir
    )
    assert isinstance(quality, gate.QualityReport)
    assert not (quality_dir / "quality_gate.json").exists()

    fallback = planner.create_fallback_plan(
        quality_report=quality,
        quality_gate_path=quality_dir / "quality_gate.json",
        pdf_path=pdf_path,
        output_dir=fallback_dir,
    )
    assert isinstance(fallback, planner.FallbackPlan)
    assert not (fallback_dir / "fallback_execution_manifest.json").exists()

    capability = router.create_capability_plan(
        fallback_plan=fallback,
        manifest_path=fallback_dir / "fallback_execution_manifest.json",
    )
    assert isinstance(capability, router.CapabilityPlan)
    assert capability.data["tasks"][0]["capability_route"] == "PAGE_DOCUMENT_OCR"
    assert not (routing_dir / "provider_plan.json").exists()

    gate.write_quality_report(quality, quality_dir)
    planner.write_fallback_plan(fallback, fallback_dir)
    router.write_capability_plan(capability, routing_dir)
    artifacts = [
        quality_dir / "quality_gate.json", quality_dir / "quality_gate.md",
        fallback_dir / "fallback_execution_manifest.json",
        fallback_dir / "fallback_execution_manifest.md",
        routing_dir / "provider_plan.json", routing_dir / "provider_plan.md",
    ]
    original_bytes = {path: path.read_bytes() for path in artifacts}

    gate.run_quality_gate(manifest_path=manifest_path, pdf_path=pdf_path, output_dir=quality_dir)
    planner.run_fallback_planning(
        quality_gate_path=quality_dir / "quality_gate.json",
        pdf_path=pdf_path, output_dir=fallback_dir,
    )
    router.run_capability_routing(
        manifest_path=fallback_dir / "fallback_execution_manifest.json",
        output_dir=routing_dir,
    )
    for path in artifacts:
        assert path.read_bytes() == original_bytes[path]
