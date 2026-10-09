"""Internal document boundaries must not imply section or record ownership."""

from copy import deepcopy
from dataclasses import replace

import pytest

from pdffast.structure_reconciliation.adjudication import RecoveredSectionProposal
from pdffast.structure_reconciliation.document_units import (
    DocumentUnit,
    create_document_units,
    section_parent_map,
)
from pdffast.structure_reconciliation.preview import preview_reconciled_structure


def _native(*owners: str | None) -> dict:
    sections = [
        {"section_id": owner, "title": f"Native {owner}", "anchor_page": page,
         "start_page": page, "end_page": page}
        for page, owner in enumerate(owners, 1) if owner
    ]
    return {
        "source_file": "fixture.pdf", "page_count": len(owners),
        "sections": sections,
        "pages": [{"page_number": page, "section_id": owner}
                  for page, owner in enumerate(owners, 1)],
        "unresolved_regions": [],
    }


def _proposal(page: int, *parts: str, decision: str = "ACCEPTED_PROPOSAL",
              role: str = "DOCUMENT_BOUNDARY_CANDIDATE",
              proposal_id: str | None = None) -> RecoveredSectionProposal:
    return RecoveredSectionProposal(
        proposal_id=proposal_id or f"recovered:p{page:04d}:01", page_number=page,
        title_parts=parts,
        candidate_refs=tuple(f"p{page:04d}:candidate:{i}" for i in range(len(parts))),
        suggested_role=role, evidence_kinds=("OCR_VISUAL_LINE",),
        providers=("fixture",), task_ids=(f"task-{page}",), signals={},
        conflicts=(), structure_strength="STRONG", decision=decision, reason="fixture",
    )


def _units(native: dict, *proposals: RecoveredSectionProposal) -> tuple[DocumentUnit, ...]:
    return create_document_units(preview_reconciled_structure(native, proposals))


def test_anchor_can_exist_without_range() -> None:
    unit = _units(_native(None), _proposal(1, "合同书"))[1]
    assert unit.anchor_page == 1
    assert unit.range_status == "UNRESOLVED"
    assert unit.page_range is None


def test_document_unit_can_exist_without_sections() -> None:
    primary, recovered = _units(_native(None), _proposal(1, "封面"))
    assert primary.section_ids == ()
    assert recovered.section_ids == ()


def test_native_section_is_not_implicitly_owned_by_primary() -> None:
    native = _native("native-1", None, "native-3")
    units = _units(native, _proposal(2, "附件"))
    assert [section["section_id"] for section in native["sections"]] == ["native-1", "native-3"]
    assert units[0].source == "NATIVE"
    assert units[0].role == "PRIMARY"
    assert units[0].section_ids == ()
    assert section_parent_map(units) == {}


def test_confirmed_section_parent_can_be_recorded() -> None:
    primary = _units(_native("native-1"))[0]
    confirmed = replace(primary, section_ids=("native-1",))
    assert section_parent_map((confirmed,)) == {"native-1": confirmed.document_id}


def test_section_cannot_belong_to_multiple_document_units() -> None:
    primary = replace(_units(_native("native-1"))[0], section_ids=("native-1",))
    duplicate = replace(primary, document_id="another", section_ids=("native-1",))
    with pytest.raises(ValueError, match="multiple document units"):
        section_parent_map((primary, duplicate))


def test_recovered_document_anchor_creates_document_unit_not_section() -> None:
    units = _units(_native(None), _proposal(1, "项目合同书"))
    assert len(units) == 2
    assert units[1].source == "RECOVERED"
    assert units[1].role == "UNKNOWN"
    assert units[1].section_ids == ()
    assert section_parent_map(units) == {}


def test_recovered_section_anchor_does_not_create_document_unit() -> None:
    units = _units(_native(None), _proposal(1, "一、研究内容", role="SECTION_CANDIDATE"))
    assert len(units) == 1
    assert units[0].role == "PRIMARY"


@pytest.mark.parametrize("decision", ["AMBIGUOUS", "REJECTED"])
def test_unaccepted_proposal_does_not_create_document_unit(decision: str) -> None:
    units = _units(_native(None), _proposal(1, "待判标题", decision=decision))
    assert len(units) == 1


def test_same_title_on_different_pages_has_distinct_document_ids() -> None:
    units = _units(_native(None, None), _proposal(1, "通知"), _proposal(2, "通知"))
    assert units[1].title_parts == units[2].title_parts == ("通知",)
    assert units[1].document_id != units[2].document_id


def test_document_id_is_deterministic_for_same_structure_input() -> None:
    native = _native(None)
    proposals = (_proposal(1, "合同书"),)
    first = _units(native, *proposals)
    second = _units(deepcopy(native), *proposals)
    assert [unit.document_id for unit in first] == [unit.document_id for unit in second]


def test_document_unit_creation_does_not_assign_records() -> None:
    native = _native(None)
    native["records"] = [{"record_id": "r1", "section_id": None, "source_page": 1}]
    before = deepcopy(native)
    _units(native, _proposal(1, "合同书"))
    assert native == before
    assert "document_id" not in native["records"][0]


def test_document_unit_contract_does_not_modify_canonical(tmp_path) -> None:
    canonical = tmp_path / "canonical_document.json"
    canonical.write_bytes(b'{"records": [{"record_id": "r1"}]}')
    before = canonical.read_bytes()
    _units(_native(None), _proposal(1, "合同书"))
    assert canonical.read_bytes() == before


def test_unresolved_anchor_cannot_claim_even_its_own_page_as_range() -> None:
    unit = _units(_native(None), _proposal(1, "合同书"))[1]
    with pytest.raises(ValueError, match="unresolved range"):
        replace(unit, page_range=(1, 1))
