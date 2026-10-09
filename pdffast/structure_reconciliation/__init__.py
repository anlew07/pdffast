"""Internal evidence boundary for future structure reconciliation."""

from .heading_candidates import (
    RecoveredHeadingCandidate,
    RecoveredHeadingDiagnostic,
    RecoveredHeadingReport,
    diagnose_recovered_heading_candidates,
    extract_recovered_heading_candidates,
)
from .adjudication import (
    CandidateJudgment,
    RecoveredSectionProposal,
    RecoveredStructureReport,
    adjudicate_recovered_heading_candidates,
)
from .preview import (
    IgnoredStructureProposal,
    ReconciledStructurePreview,
    RecoveredDocumentAnchor,
    RecoveredSectionAnchor,
    RecoveredStructureAnchor,
    StructurePreviewConflict,
    preview_reconciled_structure,
)
from .document_units import DocumentUnit, create_document_units, section_parent_map
from .anchor_admission import DocumentAnchorAdmissionDecision, admit_recovered_document_anchors
from .coverage import DocumentCoverageResult, resolve_document_coverages

__all__ = [
    "RecoveredHeadingCandidate",
    "RecoveredHeadingDiagnostic",
    "RecoveredHeadingReport",
    "diagnose_recovered_heading_candidates",
    "extract_recovered_heading_candidates",
    "CandidateJudgment",
    "RecoveredSectionProposal",
    "RecoveredStructureReport",
    "adjudicate_recovered_heading_candidates",
    "IgnoredStructureProposal",
    "ReconciledStructurePreview",
    "RecoveredDocumentAnchor",
    "RecoveredSectionAnchor",
    "RecoveredStructureAnchor",
    "StructurePreviewConflict",
    "preview_reconciled_structure",
    "DocumentUnit",
    "create_document_units",
    "section_parent_map",
    "DocumentAnchorAdmissionDecision",
    "admit_recovered_document_anchors",
    "DocumentCoverageResult",
    "resolve_document_coverages",
]
