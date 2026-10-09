"""Page Structure consumes the profiler's shared observation without reopening JSONL."""

import hashlib
import json
import os
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import pytest

from pdffast.errors import ParseExecutionError
from pdffast.native import sections, structure, tables, text_flow
from pdffast.pipeline import runner
from pdffast.pipeline.context import PipelineContext
from pdffast.quality import evidence


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


@pytest.mark.parametrize(
    ("case_id", "profile_sha256", "snapshot_sha256", "alignment_sha256", "stage4_sha256", "pages_sha256", "block_count"),
    [
        (
            "case_002",
            "027698de675c587becfdf830f388dfb5c002b755f34583ade531a8aed300a8be",
            "f006e74c9a3c847b6d98c1a6dd09d64850355e0445f0313a9b00460e8504fee2",
            "65f8657cde8fb1b4ca87ef09da4040849684ae14ba3df888dd7095d095a994a2",
            "3639575a0c5af216cf96d60b3759d64c2c0863bfc4aaae8afe499150fa3bae68",
            "e22c82040bb8d5db7c4f491a9185e9f33ff6e0e93aa3c32e96a4495804e51436",
            57,
        ),
        (
            "case_003",
            "1ed6b8ae7e58a03b17cca38162efe195ea686915b48bec8c28b0e067b68fe022",
            "d9c2f1d77b170672ee8159a31872e7fdee004bd8a062063bb7a1776a50429dfb",
            "47b1859877758e0c4090c608f99759cb3cb787e3762011104a48ad530fa6268a",
            "bad02207507891bfaa4c34c25971d4df4167fb1517dbac871cd3f189c7892bff",
            "9501152135aaf0c0081ce2d0c2aa829d585a41499bed3dfb02cb9ecc1ce792e4",
            537,
        ),
        (
            "case_004",
            "a8b7f1cf3a9ef884b8ea9a5514a76b67469fe460a72eaf19d2fd4a3ed3d27012",
            "cd3aa7ee1ac428c5b1678bf408f84df08497d3feb2b3d623c18f2b0ee9263da2",
            "284935ddb980f3de5340b140dc25f9bb90cdf7f775e1c36fc358d97074417e94",
            "2ffe9036bf4a80a5873894ecfef13d6054670842c1dfcc5cda37d3f4a31d3018",
            "b549d6e559de530acf9e9193a0a56da7f47599a524abbb2363807a74db10cf2c",
            540,
        ),
    ],
)
def test_real_snapshot_to_structure_object_file_parity(
    tmp_path: Path,
    case_id: str,
    profile_sha256: str,
    snapshot_sha256: str,
    alignment_sha256: str,
    stage4_sha256: str,
    pages_sha256: str,
    block_count: int,
) -> None:
    reference_root = os.environ.get("PDFFAST_REFERENCE_ROOT")
    if not reference_root:
        pytest.skip("PDFFAST_REFERENCE_ROOT is required for this real PDF")
    pdf = Path(reference_root) / "benchmark/samples/real" / f"{case_id}.pdf"
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

    frozen_root = (Path("outputs/final_structure_regression") / case_id).resolve()
    assert hashlib.sha256(snapshot_path.read_bytes()).hexdigest() == snapshot_sha256
    assert profile_path.read_bytes() == json.dumps(profile, ensure_ascii=False, indent=2).encode("utf-8")
    frozen_profile = deepcopy(profile)
    frozen_profile["snapshot_file"] = str(frozen_root / "01_stage1/page_snapshot.jsonl")
    assert hashlib.sha256(json.dumps(frozen_profile, ensure_ascii=False, indent=2).encode("utf-8")).hexdigest() == profile_sha256
    assert shared_digest() == snapshot_sha256
    alignment = sections.run_section_discovery(
        profile_path=profile_path,
        snapshot_path=snapshot_path,
        output_path=alignment_path,
        profile=profile,
        snapshot_pages=snapshot_pages,
    )
    assert shared_digest() == snapshot_sha256
    assert hashlib.sha256(alignment_path.read_bytes()).hexdigest() == alignment_sha256
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
    assert shared_digest() == snapshot_sha256
    assert alignment == before_alignment
    assert profile == before_profile
    assert profile_path.read_bytes() == json.dumps(profile, ensure_ascii=False, indent=2).encode("utf-8")
    assert hashlib.sha256(alignment_path.read_bytes()).hexdigest() == alignment_sha256
    file_result = structure.run_page_structure(
        snapshot_path=snapshot_path,
        profile_path=profile_path,
        alignment_path=alignment_path,
        output_path=file_path,
    )
    assert object_result == file_result
    assert object_path.read_bytes() == file_path.read_bytes()
    frozen_stage4 = tmp_path / "04/frozen-provenance.json"
    frozen_result = structure.run_page_structure(
        snapshot_path=frozen_root / "01_stage1/page_snapshot.jsonl",
        profile_path=frozen_root / "01_stage1/page_profile.json",
        alignment_path=frozen_root / "03_stage3/section_alignment.json",
        output_path=frozen_stage4,
        snapshot_meta=snapshot_meta,
        snapshot_pages=snapshot_pages,
        section_alignment=alignment,
        profile=profile,
    )
    assert frozen_result == json.loads((frozen_root / "04_stage4/page_structure.json").read_text(encoding="utf-8"))
    assert hashlib.sha256(frozen_stage4.read_bytes()).hexdigest() == stage4_sha256
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
    assert shared_digest() == snapshot_sha256
    assert table_result == file_table_result
    for name in ("result.json", "result.md", "logical_tables.md"):
        assert (tmp_path / "05_stage5" / name).read_bytes() == (tmp_path / "05_file" / name).read_bytes()
        assert (tmp_path / "05_stage5" / name).read_bytes() == (frozen_root / "05_stage5" / name).read_bytes()

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
    assert shared_digest() == snapshot_sha256
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
    assert stage6_files == {path.name for path in (frozen_root / "06_stage6").iterdir()}
    for name in stage6_files:
        assert (tmp_path / "06_stage6" / name).read_bytes() == (frozen_root / "06_stage6" / name).read_bytes()
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
    assert shared_digest() == snapshot_sha256
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
    frozen_evidence = json.loads((frozen_root / "07_stage7/evidence_manifest.json").read_text(encoding="utf-8"))
    current_evidence = deepcopy(report.data)
    current_evidence["inputs"] = frozen_evidence["inputs"]
    assert current_evidence == frozen_evidence
    assert (json.dumps(current_evidence, ensure_ascii=False, indent=2) + "\n").encode("utf-8") == (
        frozen_root / "07_stage7/evidence_manifest.json"
    ).read_bytes()
    assert object_result == before_structure
    del snapshot_pages
    pages_bytes = json.dumps(
        object_result["pages"], ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    assert hashlib.sha256(pages_bytes).hexdigest() == pages_sha256
    assert sum(len(page["blocks"]) for page in object_result["pages"]) == block_count
    if case_id == "case_004":
        pages = {page["page_number"]: page for page in object_result["pages"]}
        assert [pages[n]["document_structure"]["section_id"] for n in (25, 48, 80, 90, 101, 114)] == [
            "observed_section_011", "observed_section_012", "observed_section_013",
            "observed_section_014", "observed_section_015", "observed_section_015",
        ]
