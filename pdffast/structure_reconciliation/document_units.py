"""Internal document-unit contract; no page or record ownership is inferred here."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Iterable

from .anchor_admission import DocumentAnchorAdmissionDecision
from .preview import ReconciledStructurePreview, RecoveredDocumentAnchor


@dataclass(frozen=True)
class DocumentUnit:
    document_id: str
    role: str
    source: str
    anchor_ref: str | None
    anchor_page: int | None
    title_parts: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    range_status: str
    page_range: tuple[int, int] | None
    section_ids: tuple[str, ...]
    anchor_status: str = "NOT_APPLICABLE"

    def __post_init__(self) -> None:
        if not self.document_id:
            raise ValueError("document_id is required")
        if self.role not in {"PRIMARY", "ATTACHED", "UNKNOWN"}:
            raise ValueError(f"unsupported document role: {self.role}")
        if self.source not in {"NATIVE", "RECOVERED"}:
            raise ValueError(f"unsupported document source: {self.source}")
        if self.anchor_page is not None and self.anchor_page < 1:
            raise ValueError("anchor_page must be positive")
        if (self.anchor_page is None) != (self.anchor_ref is None):
            raise ValueError("anchor_page and anchor_ref must be provided together")
        if self.source == "RECOVERED" and self.anchor_page is None:
            raise ValueError("recovered document requires an anchor")
        if self.source == "NATIVE" and self.anchor_status != "NOT_APPLICABLE":
            raise ValueError("Native document cannot have recovered anchor status")
        if self.source == "RECOVERED" and self.anchor_status not in {"PROPOSED", "ANCHOR_CONFIRMED"}:
            raise ValueError("recovered document requires proposed or confirmed anchor status")
        if self.range_status == "UNRESOLVED":
            if self.page_range is not None:
                raise ValueError("unresolved range cannot claim pages")
        elif self.range_status in {"PARTIAL", "RESOLVED"}:
            if self.page_range is None or not (1 <= self.page_range[0] <= self.page_range[1]):
                raise ValueError("coverage span requires valid page bounds")
        else:
            raise ValueError(f"unsupported range status: {self.range_status}")
        if len(self.section_ids) != len(set(self.section_ids)):
            raise ValueError("duplicate section in document unit")


def section_parent_map(units: Iterable[DocumentUnit]) -> dict[str, str]:
    """Validate that each section has at most one document parent."""
    parents: dict[str, str] = {}
    document_ids: set[str] = set()
    for unit in units:
        if unit.document_id in document_ids:
            raise ValueError(f"duplicate document_id: {unit.document_id}")
        document_ids.add(unit.document_id)
        for section_id in unit.section_ids:
            if section_id in parents:
                raise ValueError(f"section belongs to multiple document units: {section_id}")
            parents[section_id] = unit.document_id
    return parents


def _recovered_document_id(anchor: RecoveredDocumentAnchor) -> str:
    identity = json.dumps(
        [anchor.page_number, anchor.anchor_id, list(anchor.candidate_refs)],
        ensure_ascii=False, separators=(",", ":"),
    )
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12]
    return f"document:recovered:p{anchor.page_number:04d}:{digest}"


def create_document_units(
    preview: ReconciledStructurePreview,
    *,
    admissions: Iterable[DocumentAnchorAdmissionDecision] = (),
) -> tuple[DocumentUnit, ...]:
    """Create explicit provisional/admitted units without inferring page ownership."""
    confirmed: dict[str, DocumentAnchorAdmissionDecision] = {}
    for decision in admissions:
        if decision.status != "ANCHOR_CONFIRMED":
            continue
        if decision.proposal_id in confirmed:
            raise ValueError(f"duplicate anchor admission: {decision.proposal_id}")
        confirmed[decision.proposal_id] = decision
    units = [DocumentUnit(
        document_id="document:native:primary", role="PRIMARY", source="NATIVE",
        anchor_ref=None, anchor_page=None, title_parts=(), evidence_refs=(),
        range_status="UNRESOLVED", page_range=None, section_ids=(),
    )]
    for anchor in preview.recovered_anchors:
        if not isinstance(anchor, RecoveredDocumentAnchor):
            continue
        if anchor.source != "RECOVERED" or anchor.range_status != "UNRESOLVED" or anchor.page_range is not None:
            raise ValueError("recovered document anchor must have unresolved range")
        decision = confirmed.pop(anchor.proposal_id, None)
        if decision is not None and (
            decision.anchor_ref != anchor.anchor_id
            or decision.page_number != anchor.page_number
            or decision.candidate_refs != anchor.candidate_refs
        ):
            raise ValueError("anchor admission does not match preview anchor")
        units.append(DocumentUnit(
            document_id=_recovered_document_id(anchor), role="UNKNOWN",
            source="RECOVERED", anchor_ref=anchor.anchor_id,
            anchor_page=anchor.page_number,
            title_parts=anchor.original_text_parts,
            evidence_refs=anchor.candidate_refs,
            range_status="UNRESOLVED", page_range=None, section_ids=(),
            anchor_status="ANCHOR_CONFIRMED" if decision is not None else "PROPOSED",
        ))
    if confirmed:
        raise ValueError("confirmed anchor admission has no preview anchor")
    section_parent_map(units)
    return tuple(units)
