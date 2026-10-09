"""Real-PDF characterization of page ownership after generic heading discovery."""

import os
from pathlib import Path

import pytest

from pdffast.native.profiler import run_profiler
from pdffast.native.sections import diagnose_page_ownership, load_snapshot_pages, run_section_discovery


def _native_sections(tmp_path: Path, case: str) -> tuple[dict, dict[int, dict], list[dict]]:
    root = os.environ.get("PDFFAST_REFERENCE_ROOT")
    if not root:
        pytest.skip("PDFFAST_REFERENCE_ROOT is required for this real PDF")
    pdf = Path(root).resolve() / "benchmark/samples/real" / f"case_{case}.pdf"
    profile = tmp_path / "page_profile.json"
    snapshot = tmp_path / "page_snapshot.jsonl"
    alignment = tmp_path / "section_alignment.json"
    run_profiler(pdf_path=pdf, profile_output=profile, snapshot_output=snapshot, table_mode="auto")
    result = run_section_discovery(profile_path=profile, snapshot_path=snapshot, output_path=alignment)
    pages = load_snapshot_pages(snapshot)
    diagnostics = diagnose_page_ownership(page_count=result["page_count"], snapshot_pages=pages)
    return result, pages, diagnostics


def test_case_003_preserves_independent_anchors_and_unresolved_scans(tmp_path: Path) -> None:
    result, pages, diagnostics = _native_sections(tmp_path, "003")
    anchors = {section["anchor_page"]: section for section in result["sections"]}
    assert len(anchors) == 16
    assert anchors[19]["title"] == anchors[20]["title"] == anchors[24]["title"]
    assert len({anchors[page]["section_id"] for page in (19, 20, 24)}) == 3
    assert [(region["start_page"], region["end_page"]) for region in result["unresolved_regions"]] == [
        (1, 1), (21, 23), (25, 27), (29, 64), (66, 66),
    ]
    assert diagnostics[20]["decision"] == "UNRESOLVED"
    assert "page_dimensions_changed" in diagnostics[20]["boundary_signals"]
    assert all(section["title"] in pages[section["anchor_page"]]["native_text"] for section in result["sections"])


def test_case_004_internal_page_and_item_numbers_confirm_tail(tmp_path: Path) -> None:
    result, pages, diagnostics = _native_sections(tmp_path, "004")
    anchors = {section["anchor_page"]: section for section in result["sections"]}
    assert len(anchors) == 15
    assert {25, 48, 80, 90, 101}.issubset(anchors)
    assert anchors[101]["end_page"] == 114
    assert all(result["pages"][page - 1]["section_id"] == anchors[101]["section_id"] for page in range(102, 115))
    assert all(result["pages"][page - 1]["section_id"] is None for page in range(21, 25))
    assert [(region["start_page"], region["end_page"]) for region in result["unresolved_regions"]] == [(1, 1), (21, 24)]
    assert all(
        diagnostics[page - 1]["decision"] == "CONTINUE"
        and "internal_page_number_consecutive" in diagnostics[page - 1]["continuity_signals"]
        and "item_number_matches_section" in diagnostics[page - 1]["continuity_signals"]
        for page in range(102, 115)
    )
    assert all(section["title"] in pages[section["anchor_page"]]["native_text"] for section in result["sections"])
