"""Real-PDF profiler-to-section object/file parity for the current V3 path."""

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from pdffast.native import profiler, sections

pytestmark = pytest.mark.regression


@pytest.mark.parametrize(
    ("case_id", "unresolved"),
    [
        ("case_003", [(1, 1), (21, 23), (25, 27), (29, 64), (66, 66)]),
        ("case_004", [(1, 1), (21, 24)]),
    ],
)
def test_real_snapshot_and_section_object_file_parity(
    tmp_path: Path,
    case_id: str,
    unresolved: list[tuple[int, int]],
) -> None:
    data_root = os.environ.get("PDFFAST_TEST_DATA_ROOT")
    if not data_root:
        pytest.skip("PDFFAST_TEST_DATA_ROOT is required for real-PDF regression")
    pdf = Path(data_root).resolve() / "benchmark/samples/real" / f"{case_id}.pdf"
    profile_path = tmp_path / "01/page_profile.json"
    snapshot_path = tmp_path / "01/page_snapshot.jsonl"
    object_path = tmp_path / "03/object.json"
    file_path = tmp_path / "03/file.json"
    snapshot_pages: dict[int, dict] = {}
    profile = profiler.run_profiler(
        pdf_path=pdf,
        profile_output=profile_path,
        snapshot_output=snapshot_path,
        snapshot_pages=snapshot_pages,
    )

    original_open = Path.open

    def forbid_snapshot_read(path: Path, mode: str = "r", *args: object, **kwargs: object):
        if path == snapshot_path and "r" in mode:
            raise AssertionError("Section Discovery reopened snapshot JSONL")
        return original_open(path, mode, *args, **kwargs)

    with patch.object(Path, "open", forbid_snapshot_read):
        object_result = sections.run_section_discovery(
            profile_path=profile_path,
            snapshot_path=snapshot_path,
            output_path=object_path,
            profile=profile,
            snapshot_pages=snapshot_pages,
        )
    candidate_diagnostics = sections.diagnose_section_candidates(
        page_count=profile["page_count"], snapshot_pages=snapshot_pages
    )
    ownership_diagnostics = sections.diagnose_page_ownership(
        page_count=profile["page_count"], snapshot_pages=snapshot_pages
    )
    del snapshot_pages

    file_result = sections.run_section_discovery(
        profile_path=profile_path, snapshot_path=snapshot_path, output_path=file_path
    )
    assert object_result == file_result
    assert object_path.read_bytes() == file_path.read_bytes()
    file_pages = sections.load_snapshot_pages(snapshot_path)
    assert sections.diagnose_section_candidates(
        page_count=profile["page_count"], snapshot_pages=file_pages
    ) == candidate_diagnostics
    assert sections.diagnose_page_ownership(
        page_count=profile["page_count"], snapshot_pages=file_pages
    ) == ownership_diagnostics
    assert [(r["start_page"], r["end_page"]) for r in object_result["unresolved_regions"]] == unresolved

    if case_id == "case_003":
        title = "关于国家自然科学基金资助项目批准及有关事项的通知"
        assert [s["anchor_page"] for s in object_result["sections"] if s["title"] == title] == [19, 20, 24]
    else:
        anchors = {s["anchor_page"]: s for s in object_result["sections"]}
        assert all(page in anchors for page in (25, 48, 80, 90, 101))
        assert anchors[101]["end_page"] == 114
