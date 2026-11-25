"""Shared deterministic fixtures for PDFFast V3 tests."""

from __future__ import annotations

import pytest


@pytest.fixture
def v3_pipeline_inputs() -> dict:
    """Small in-memory V3 input set; no PDF, prior run, or workspace is required."""
    source_file = "fixture://pdffast-v3/sample.pdf"
    bbox = {"x0": 10.0, "top": 10.0, "x1": 90.0, "bottom": 90.0}
    native_flow = {
        "source_file": source_file,
        "page_count": 1,
        "artifact_role": "native_parser_final_flow",
        "final_llm_document": False,
        "record_count": 2,
        "page_index": [{"page_number": 1, "status": "NATIVE"}],
        "sections": [{
            "section_id": "section-1",
            "section_key": "section-1",
            "section_title": "一、原生内容",
            "page_numbers": [1],
            "record_ids": ["native-paragraph-1", "native-image-1"],
        }],
        "records": [
            {
                "record_id": "native-paragraph-1",
                "record_type": "paragraph",
                "source_page": 1,
                "section_id": "section-1",
                "page_flow_order": 1,
                "text": "V3 原生正文",
            },
            {
                "record_id": "native-image-1",
                "record_type": "image_ref",
                "source_page": 1,
                "source_block_id": "block-image-1",
                "page_flow_order": 2,
                "bbox": bbox,
            },
        ],
    }
    quality_gate = {
        "source_file": source_file,
        "page_count": 1,
        "stage": 8,
        "name": "quality_gate",
        "pages": [{
            "page_number": 1,
            "decision": "NATIVE_PASS_WITH_NON_TEXT",
            "route": "NATIVE",
            "non_text_assessment": {
                "regions": [{
                    "region_id": "region-1",
                    "region_type": "image",
                    "action": "REGION_FALLBACK_REQUIRED",
                    "source_refs": ["stage4:block:block-image-1"],
                    "bbox": bbox,
                }],
            },
        }],
    }
    task = {
        "task_id": "task-region-1",
        "task_type": "REGION_FALLBACK",
        "page_number": 1,
        "source_id": "region-1",
        "source_bbox": bbox,
        "capability_route": "REGION_MULTIMODAL_PARSE",
        "stage8_decision": "NATIVE_PASS_WITH_NON_TEXT",
        "stage8_route": "REGION_FALLBACK_REQUIRED",
        "stage8_gate_state": "HARD_FALLBACK",
    }
    capability_plan = {
        "source_file": source_file,
        "page_count": 1,
        "stage": 9,
        "artifact_role": "fallback_provider_capability_plan",
        "tasks": [task],
    }
    selected_index = {
        "source_file": source_file,
        "stage": 9,
        "substage": "9.8",
        "task_count": 1,
        "items": [{"task_id": "task-region-1"}],
    }
    selected_predictions = [{
        "task_id": "task-region-1",
        "task_type": "REGION_FALLBACK",
        "page_number": 1,
        "source_id": "region-1",
        "capability_route": "REGION_MULTIMODAL_PARSE",
        "ground_truth_used": False,
        "pipeline_failure": False,
        "terminal_fallback_applied": True,
        "terminal_fallback_action": "PRESERVE_SOURCE_REGION_UNRESOLVED",
        "selected_canonical": None,
        "selected_provider": None,
        "runtime_outcome": "TERMINAL_UNRESOLVED",
        "source_content_preserved": True,
    }]
    return {
        "native_flow": native_flow,
        "quality_gate": quality_gate,
        "capability_plan": capability_plan,
        "selected_index": selected_index,
        "selected_predictions": selected_predictions,
    }
