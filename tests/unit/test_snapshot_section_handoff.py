"""The profiler's page observations reach Section Discovery without a JSONL read."""

import hashlib
import json
import os
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from pdffast.errors import ParseExecutionError
from pdffast.native import profiler, sections
from pdffast.pipeline import runner
from pdffast.pipeline.context import PipelineContext


def test_profiler_snapshot_passes_directly_to_section_discovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = tmp_path / "input.pdf"
    pdf.touch()
    profile_path = tmp_path / "01/page_profile.json"
    snapshot_path = tmp_path / "01/page_snapshot.jsonl"
    object_path = tmp_path / "03/object.json"
    file_path = tmp_path / "03/file.json"
    raw_pages = [
        {"record_type": "page", "page_number": 1, "native_text": "一、基本信息\n正文", "words": [], "chars": []},
        {"record_type": "page", "page_number": 2, "native_text": "二、技术路线\n正文", "words": [], "chars": []},
    ]
    fake_pdf = SimpleNamespace(pages=[SimpleNamespace(page_number=1), SimpleNamespace(page_number=2)])
    monkeypatch.setattr(profiler.pdfplumber, "open", lambda path: nullcontext(fake_pdf))
    monkeypatch.setattr(
        profiler, "capture_page_evidence", lambda *, page, table_mode: raw_pages[page.page_number - 1]
    )
    monkeypatch.setattr(
        profiler, "profile_page_evidence", lambda page: {"page_number": page["page_number"]}
    )
    snapshot_pages: dict[int, dict] = {}

    profile = profiler.run_profiler(
        pdf_path=pdf,
        profile_output=profile_path,
        snapshot_output=snapshot_path,
        snapshot_pages=snapshot_pages,
    )
    assert snapshot_pages[1] is raw_pages[0]
    assert snapshot_pages[2] is raw_pages[1]
    assert profile_path.is_file() and snapshot_path.is_file()
    records = [json.loads(line) for line in snapshot_path.read_text(encoding="utf-8").splitlines()]
    assert records[0]["record_type"] == "meta"
    assert records[0]["page_count"] == 2
    assert records[1:] == raw_pages

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

    file_result = sections.run_section_discovery(
        profile_path=profile_path, snapshot_path=snapshot_path, output_path=file_path
    )
    assert object_result == file_result
    assert object_path.read_bytes() == file_path.read_bytes()
    assert [(item["section_id"], item["title"]) for item in object_result["sections"]] == [
        ("observed_section_001", "一、基本信息"),
        ("observed_section_002", "二、技术路线"),
    ]


def test_runner_passes_profiler_snapshot_to_sections_without_file_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = PipelineContext.create(
        project_root=tmp_path,
        pdf=tmp_path / "input.pdf",
        output_root=tmp_path / "outputs",
        run_id="snapshot-handoff",
        case_id="input",
        page_dpi=150,
        region_dpi=150,
        rapidocr_workers=1,
        table_mode="auto",
        capture_output=False,
    )
    observed = {"record_type": "page", "page_number": 1, "native_text": "一、正文"}
    profile = {"source_file": "input.pdf", "page_count": 1}
    captured = {}

    def fake_profiler(**kwargs: object) -> dict:
        kwargs["snapshot_pages"][1] = observed
        kwargs["snapshot_output"].parent.mkdir(parents=True, exist_ok=True)
        kwargs["snapshot_output"].write_text(json.dumps(observed) + "\n", encoding="utf-8")
        return profile

    def fake_sections(**kwargs: object) -> dict:
        captured.update(kwargs)
        raise RuntimeError("stop after section handoff")

    monkeypatch.setattr(runner, "run_profiler", fake_profiler)
    monkeypatch.setattr(runner, "run_section_discovery", fake_sections)
    with pytest.raises(ParseExecutionError, match="stop after section handoff"):
        runner.run_core_pipeline(context)

    assert captured["profile"] is profile
    assert captured["snapshot_pages"][1] is observed
    assert context.artifacts.snapshot.is_file()


@pytest.mark.parametrize(
    ("case_id", "snapshot_sha256", "section_sha256", "unresolved"),
    [
        (
            "case_003",
            "d9c2f1d77b170672ee8159a31872e7fdee004bd8a062063bb7a1776a50429dfb",
            "47b1859877758e0c4090c608f99759cb3cb787e3762011104a48ad530fa6268a",
            [(1, 1), (21, 23), (25, 27), (29, 64), (66, 66)],
        ),
        (
            "case_004",
            "cd3aa7ee1ac428c5b1678bf408f84df08497d3feb2b3d623c18f2b0ee9263da2",
            "284935ddb980f3de5340b140dc25f9bb90cdf7f775e1c36fc358d97074417e94",
            [(1, 1), (21, 24)],
        ),
    ],
)
def test_real_snapshot_and_section_object_file_parity(
    tmp_path: Path,
    case_id: str,
    snapshot_sha256: str,
    section_sha256: str,
    unresolved: list[tuple[int, int]],
) -> None:
    reference_root = os.environ.get("PDFFAST_REFERENCE_ROOT")
    if not reference_root:
        pytest.skip("PDFFAST_REFERENCE_ROOT is required for this real PDF")
    pdf = Path(reference_root) / "benchmark/samples/real" / f"{case_id}.pdf"
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
    assert hashlib.sha256(snapshot_path.read_bytes()).hexdigest() == snapshot_sha256

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
    assert hashlib.sha256(object_path.read_bytes()).hexdigest() == section_sha256

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
