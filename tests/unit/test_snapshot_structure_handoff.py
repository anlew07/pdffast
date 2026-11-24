"""Page Structure consumes the profiler's shared observation without reopening JSONL."""

import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import pytest

from pdffast.errors import ParseExecutionError
from pdffast.native import sections, structure, tables, text_flow
from pdffast.pipeline import runner
from pdffast.pipeline.context import PipelineContext


def test_shared_snapshot_survives_sections_and_structure_without_mutation_or_file_read(
    tmp_path: Path,
) -> None:
    snapshot_path = tmp_path / "01/page_snapshot.jsonl"
    profile_path = tmp_path / "01/page_profile.json"
    alignment_path = tmp_path / "03/section_alignment.json"
    object_path = tmp_path / "04/object.json"
    file_path = tmp_path / "04/file.json"
    snapshot_meta = {
        "record_type": "meta", "snapshot_schema_version": "1.0",
        "page_scan_version": "1.0", "source_file": "input.pdf", "page_count": 2,
    }
    snapshot_pages = {
        page: {
            "record_type": "page", "page_number": page,
            "width": 600, "height": 840, "rotation": 0,
            "native_text": f"{title}\n正文", "words": [], "chars": [],
            "images": [], "lines": [], "rects": [], "curves": [],
            "table_candidates": [],
            "table_detection": {"mode": "auto", "status": "completed", "error": None},
        }
        for page, title in ((1, "一、基本信息"), (2, "二、技术路线"))
    }
    profile = {
        "source_file": "input.pdf", "page_count": 2,
        "pages": [
            {"page_number": page, "width": 600, "height": 840, "primary_type": "text_heavy"}
            for page in (1, 2)
        ],
    }
    profile_path.parent.mkdir(parents=True)
    profile_path.write_text(json.dumps(profile, ensure_ascii=False), encoding="utf-8")
    before_profile = deepcopy(profile)
    profile_bytes = profile_path.read_bytes()
    before_pages = deepcopy(snapshot_pages)
    before_meta = deepcopy(snapshot_meta)

    alignment = sections.run_section_discovery(
        profile_path=profile_path,
        snapshot_path=snapshot_path,
        output_path=alignment_path,
        profile=profile,
        snapshot_pages=snapshot_pages,
    )
    assert snapshot_pages == before_pages
    assert alignment_path.is_file()
    before_alignment = deepcopy(alignment)
    alignment_bytes = alignment_path.read_bytes()

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
    assert snapshot_pages == before_pages
    assert snapshot_meta == before_meta
    assert alignment == before_alignment
    assert profile == before_profile
    assert profile_path.read_bytes() == profile_bytes
    assert alignment_path.read_bytes() == alignment_bytes
    assert not snapshot_path.exists()
    assert object_result["page_count"] == 2
    assert [page["document_structure"]["section_id"] for page in object_result["pages"]] == [
        "observed_section_001", "observed_section_002"
    ]

    snapshot_path.write_text(
        "\n".join(json.dumps(record, ensure_ascii=False) for record in (snapshot_meta, *snapshot_pages.values())) + "\n",
        encoding="utf-8",
    )
    file_result = structure.run_page_structure(
        snapshot_path=snapshot_path,
        profile_path=profile_path,
        alignment_path=alignment_path,
        output_path=file_path,
    )
    assert object_result == file_result
    assert object_path.read_bytes() == file_path.read_bytes()
    before_structure = deepcopy(object_result)
    original_open = Path.open

    def forbid_stage4_read(path: Path, mode: str = "r", *args: object, **kwargs: object):
        if path in (object_path, snapshot_path) and "r" in mode:
            raise AssertionError(f"Table Recovery reopened {path}")
        return original_open(path, mode, *args, **kwargs)

    with patch.object(Path, "open", forbid_stage4_read):
        table_object = tables.run_table_recovery(
            structure_path=object_path,
            snapshot_path=snapshot_path,
            output_dir=tmp_path / "05/object",
            page_structure=object_result,
            snapshot_pages=snapshot_pages,
        )
    table_file = tables.run_table_recovery(
        structure_path=object_path,
        snapshot_path=snapshot_path,
        output_dir=tmp_path / "05/file",
    )
    assert object_result == before_structure
    assert snapshot_pages == before_pages
    assert table_object == table_file
    for name in ("result.json", "result.md", "logical_tables.md"):
        assert (tmp_path / "05/object" / name).read_bytes() == (tmp_path / "05/file" / name).read_bytes()


def test_runner_passes_same_snapshot_through_sections_to_page_structure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = PipelineContext.create(
        project_root=tmp_path,
        pdf=tmp_path / "input.pdf",
        output_root=tmp_path / "outputs",
        run_id="structure-handoff",
        case_id="input",
        page_dpi=150,
        region_dpi=150,
        rapidocr_workers=1,
        table_mode="auto",
        capture_output=False,
    )
    page = {"record_type": "page", "page_number": 1, "native_text": "一、正文"}
    meta = {"record_type": "meta", "source_file": "input.pdf", "page_count": 1}
    profile = {"source_file": "input.pdf", "page_count": 1}
    seen = {}
    alignment = {"sections": [], "pages": []}

    def fake_profiler(**kwargs: object) -> dict:
        kwargs["snapshot_pages"][1] = page
        kwargs["snapshot_meta"].update(meta)
        path = kwargs["snapshot_output"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(meta) + "\n" + json.dumps(page) + "\n", encoding="utf-8")
        return profile

    def fake_sections(**kwargs: object) -> dict:
        seen["section_pages"] = kwargs["snapshot_pages"]
        assert kwargs["snapshot_pages"][1] is page
        return alignment

    def fake_structure(**kwargs: object) -> dict:
        seen["structure_pages"] = kwargs["snapshot_pages"]
        seen["structure_meta"] = kwargs["snapshot_meta"]
        seen["structure_alignment"] = kwargs.get("section_alignment")
        seen["structure_profile"] = kwargs.get("profile")
        raise RuntimeError("stop after Page Structure handoff")

    monkeypatch.setattr(runner, "run_profiler", fake_profiler)
    monkeypatch.setattr(runner, "run_section_discovery", fake_sections)
    monkeypatch.setattr(runner, "run_page_structure", fake_structure)
    with pytest.raises(ParseExecutionError, match="stop after Page Structure handoff"):
        runner.run_core_pipeline(context)

    assert seen["section_pages"] is seen["structure_pages"]
    assert seen["structure_pages"][1] is page
    assert seen["structure_meta"] == meta
    assert seen["structure_alignment"] is alignment
    assert seen["structure_profile"] is profile
    assert context.artifacts.snapshot.is_file()


