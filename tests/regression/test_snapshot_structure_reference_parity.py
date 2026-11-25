"""Real-PDF object/file parity for the current V3 native handoff."""

import hashlib
import json
import os
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import pytest

from pdffast.native import sections, structure, tables, text_flow
from pdffast.pipeline import runner
from pdffast.quality import evidence

pytestmark = pytest.mark.regression


@pytest.mark.parametrize(
    ("case_id", "block_count", "expected_record_count"),
    [("case_002", 57, 71), ("case_003", 537, 631), ("case_004", 540, None)],
)
def test_real_snapshot_to_structure_object_file_parity(
    tmp_path: Path,
    case_id: str,
    block_count: int,
    expected_record_count: int | None,
) -> None:
    data_root = os.environ.get("PDFFAST_TEST_DATA_ROOT")
    if not data_root:
        pytest.skip("PDFFAST_TEST_DATA_ROOT is required for real-PDF regression")
    pdf = Path(data_root).resolve() / "benchmark/samples/real" / f"{case_id}.pdf"
    profile_path = tmp_path / "01/page_profile.json"
    snapshot_path = tmp_path / "01/page_snapshot.jsonl"
    alignment_path = tmp_path / "03/section_alignment.json"
    object_path = tmp_path / "04/object.json"
    file_path = tmp_path / "04/file.json"
    snapshot_pages: dict[int, dict] = {}
    snapshot_meta: dict = {}
    profile = runner.run_profiler(
        pdf_path=pdf,
        profile_output=profile_path,
        snapshot_output=snapshot_path,
        snapshot_pages=snapshot_pages,
        snapshot_meta=snapshot_meta,
    )

    def shared_digest() -> str:
        digest = hashlib.sha256()
        for item in (snapshot_meta, *snapshot_pages.values()):
            digest.update(json.dumps(item, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n")
        return digest.hexdigest()

    initial_shared_digest = shared_digest()
    assert profile_path.read_bytes() == json.dumps(profile, ensure_ascii=False, indent=2).encode("utf-8")
    alignment = sections.run_section_discovery(
        profile_path=profile_path,
        snapshot_path=snapshot_path,
        output_path=alignment_path,
        profile=profile,
        snapshot_pages=snapshot_pages,
    )
    assert shared_digest() == initial_shared_digest
    alignment_bytes = alignment_path.read_bytes()
    before_alignment = deepcopy(alignment)
    before_profile = deepcopy(profile)
    original_open = Path.open

    def forbid_snapshot_read(path: Path, mode: str = "r", *args: object, **kwargs: object):
        if path in (snapshot_path, alignment_path, profile_path) and "r" in mode:
            raise AssertionError(f"Page Structure reopened {path}")
        return original_open(path, mode, *args, **kwargs)

    with patch.object(Path, "open", forbid_snapshot_read):
        object_result = structure.run_page_structure(
            snapshot_path=snapshot_path,
            profile_path=profile_path,
            alignment_path=alignment_path,
            output_path=object_path,
            snapshot_meta=snapshot_meta,
            snapshot_pages=snapshot_pages,
            section_alignment=alignment,
            profile=profile,
        )
    assert shared_digest() == initial_shared_digest
    assert alignment == before_alignment
    assert profile == before_profile
    assert profile_path.read_bytes() == json.dumps(profile, ensure_ascii=False, indent=2).encode("utf-8")
    assert alignment_path.read_bytes() == alignment_bytes
    file_result = structure.run_page_structure(
        snapshot_path=snapshot_path,
        profile_path=profile_path,
        alignment_path=alignment_path,
        output_path=file_path,
    )
    assert object_result == file_result
    assert object_path.read_bytes() == file_path.read_bytes()
    assert alignment == before_alignment
    assert profile == before_profile
    before_structure = deepcopy(object_result)
    original_open = Path.open

    def forbid_stage4_read(path: Path, mode: str = "r", *args: object, **kwargs: object):
        if path in (object_path, snapshot_path) and "r" in mode:
            raise AssertionError(f"Table Recovery reopened {path}")
        return original_open(path, mode, *args, **kwargs)

    with patch.object(Path, "open", forbid_stage4_read):
        table_result = tables.run_table_recovery(
            structure_path=object_path,
            snapshot_path=snapshot_path,
            output_dir=tmp_path / "05_stage5",
            page_structure=object_result,
            snapshot_pages=snapshot_pages,
        )
    file_table_result = tables.run_table_recovery(
        structure_path=object_path,
        snapshot_path=snapshot_path,
        output_dir=tmp_path / "05_file",
    )
    assert object_result == before_structure
    assert shared_digest() == initial_shared_digest
    assert table_result == file_table_result
    for name in ("result.json", "result.md", "logical_tables.md"):
        assert (tmp_path / "05_stage5" / name).read_bytes() == (tmp_path / "05_file" / name).read_bytes()

    stage5_path = tmp_path / "05_stage5/result.json"
    before_table = deepcopy(table_result)

    def forbid_stage5_read(path: Path, mode: str = "r", *args: object, **kwargs: object):
        if path == stage5_path and "r" in mode:
            raise AssertionError("TextFlow/Evidence reopened Stage5 JSON")
        return original_open(path, mode, *args, **kwargs)

    def forbid_text_flow_input_read(path: Path, mode: str = "r", *args: object, **kwargs: object):
        if path in (snapshot_path, object_path, stage5_path) and "r" in mode:
            raise AssertionError(f"TextFlow reopened {path}")
        return original_open(path, mode, *args, **kwargs)

    with patch.object(Path, "open", forbid_text_flow_input_read):
        flow = text_flow.create_text_flow_result(
            snapshot_path=snapshot_path,
            structure_path=object_path,
            table_result_path=stage5_path,
            table_result=table_result,
            snapshot_meta=snapshot_meta,
            snapshot_pages=snapshot_pages,
            page_structure=object_result,
        )
    assert shared_digest() == initial_shared_digest
    assert object_result == before_structure
    assert table_result == before_table
    text_flow.write_text_flow_result(flow, tmp_path / "06_stage6")
    file_flow = text_flow.create_text_flow_result(
        snapshot_path=snapshot_path,
        structure_path=object_path,
        table_result_path=stage5_path,
    )
    assert flow == file_flow
    text_flow.write_text_flow_result(file_flow, tmp_path / "06_file")
    stage6_files = {path.name for path in (tmp_path / "06_stage6").iterdir()}
    for name in stage6_files:
        assert (tmp_path / "06_stage6" / name).read_bytes() == (tmp_path / "06_file" / name).read_bytes()
    if case_id in ("case_002", "case_003"):
        assert flow.normalized_flow["record_count"] == {"case_002": 71, "case_003": 631}[case_id]

    before_flow = deepcopy(flow)

    def forbid_evidence_input_read(path: Path, mode: str = "r", *args: object, **kwargs: object):
        stage6_dir = tmp_path / "06_stage6"
        if path in (profile_path, snapshot_path, alignment_path, object_path, stage5_path) or path.parent == stage6_dir:
            if "r" in mode:
                raise AssertionError(f"Evidence reopened {path}")
        return original_open(path, mode, *args, **kwargs)

    with patch.object(Path, "open", forbid_evidence_input_read):
        report = evidence.create_evidence_report(
            profile_path=profile_path,
            snapshot_path=snapshot_path,
            alignment_path=alignment_path,
            structure_path=object_path,
            stage5_path=stage5_path,
            stage6_dir=tmp_path / "06_stage6",
            text_flow=flow,
            table_result=table_result,
            profile=profile,
            snapshot_meta=snapshot_meta,
            snapshot_pages=snapshot_pages,
            section_alignment=alignment,
            page_structure=object_result,
        )
    file_report = evidence.create_evidence_report(
        profile_path=profile_path,
        snapshot_path=snapshot_path,
        alignment_path=alignment_path,
        structure_path=object_path,
        stage5_path=stage5_path,
        stage6_dir=tmp_path / "06_stage6",
    )
    assert report == file_report
    assert shared_digest() == initial_shared_digest
    assert profile == before_profile
    assert alignment == before_alignment
    assert object_result == before_structure
    assert table_result == before_table
    assert flow == before_flow
    evidence.write_evidence_report(report, tmp_path / "07_stage7")
    evidence.write_evidence_report(file_report, tmp_path / "07_file")
    written_evidence = tmp_path / "07_stage7/evidence_manifest.json"
    for name in ("evidence_manifest.json", "evidence_manifest.md"):
        assert (tmp_path / "07_stage7" / name).read_bytes() == (tmp_path / "07_file" / name).read_bytes()
    assert json.loads(written_evidence.read_text(encoding="utf-8")) == report.data
    assert object_result == before_structure
    del snapshot_pages
    assert sum(len(page["blocks"]) for page in object_result["pages"]) == block_count
    if expected_record_count is not None:
        assert flow.normalized_flow["record_count"] == expected_record_count
    if case_id == "case_004":
        pages = {page["page_number"]: page for page in object_result["pages"]}
        assert [pages[n]["document_structure"]["section_id"] for n in (25, 48, 80, 90, 101, 114)] == [
            "observed_section_011", "observed_section_012", "observed_section_013",
            "observed_section_014", "observed_section_015", "observed_section_015",
        ]
