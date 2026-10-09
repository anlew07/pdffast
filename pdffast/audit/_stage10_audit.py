#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Stage 10.2.1 — Stage6 → AI-read Structural Boundary Audit

Purpose
-------
Verify that Stage9/10 fallback behaves as an overlay/replacement layer and does not
silently reorder or broadly rewrite Stage6 native content.

This is an offline audit/validation utility. It does not modify content and does not
use Ground Truth.

Checks
------
1. Stage10.1 canonical records preserve the exact Stage6 record backbone (IDs/order).
2. Native paragraph text/provenance are unchanged in Stage10.1 canonical records.
3. On Stage8 native-route pages, Stage10.2 keeps native paragraph relative order;
   any suppression must be explicitly attributable to an allowed reason.
4. REGION fallback is attached only to the original non-text visual ref position (image/vector), never to a paragraph.
5. INLINE replacement suppresses only native records fully contained in that inline context;
   partial overlaps remain native and are not suppressed by the replacement.
6. PAGE OCR fallback matches OCR_REQUIRED exactly; PAGE layout fallback matches LAYOUT_FALLBACK_REQUIRED exactly.

Inputs
------
--native-flow       Stage6 normalized_text_flow.json
--quality-gate      Stage8 quality_gate.json
--canonical         Stage10.1 canonical_document.json
--render-manifest   Stage10.2 render_manifest.json
--markdown          Stage10.2 llm_ready.md (optional when manifest names it)
--output            Output directory

Outputs
-------
structure_boundary_audit.json
structure_boundary_audit.md
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from pdffast.audit.document_units import audit_document_units

VERSION = "0.1.6"
STAGE = "10.2.1"


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be object: {path}")
    return value


def record_pages(record: dict[str, Any]) -> list[int]:
    values = record.get("source_pages")
    if isinstance(values, list):
        result = []
        for x in values:
            try:
                result.append(int(x))
            except (TypeError, ValueError):
                pass
        if result:
            return result
    value = record.get("source_page")
    if value is not None:
        try:
            return [int(value)]
        except (TypeError, ValueError):
            return []
    return []


def canonical_order(doc: dict[str, Any]) -> list[str]:
    records = [x for x in doc.get("records", []) if isinstance(x, dict)]
    all_ids = [str(x.get("record_id") or "") for x in records]
    all_set = set(all_ids)
    seen: set[str] = set()
    ordered: list[str] = []
    for section in doc.get("sections", []):
        if not isinstance(section, dict):
            continue
        for rid in section.get("record_ids") or []:
            rid = str(rid)
            if rid in all_set and rid not in seen:
                seen.add(rid)
                ordered.append(rid)
    for rid in all_ids:
        if rid and rid not in seen:
            seen.add(rid)
            ordered.append(rid)
    return ordered


def qg_page_decisions(qg: dict[str, Any]) -> dict[int, str]:
    result: dict[int, str] = {}
    for page in qg.get("pages", []):
        if not isinstance(page, dict):
            continue
        try:
            p = int(page.get("page_number"))
        except (TypeError, ValueError):
            continue
        decision = str(page.get("decision") or page.get("page_decision") or "")
        if not decision:
            # fallback to summary later
            continue
        result[p] = decision

    if result:
        return result

    pages_by_decision = ((qg.get("summary") or {}).get("pages_by_decision") or {})
    for decision, pages in pages_by_decision.items():
        if not isinstance(pages, list):
            continue
        for p in pages:
            try:
                result[int(p)] = str(decision)
            except (TypeError, ValueError):
                pass
    return result


def qg_region_index(qg: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for page in qg.get("pages", []):
        if not isinstance(page, dict):
            continue
        try:
            pn = int(page.get("page_number"))
        except (TypeError, ValueError):
            continue
        assessment = page.get("non_text_assessment") or {}
        for region in assessment.get("regions") or []:
            if not isinstance(region, dict):
                continue
            rid = str(region.get("region_id") or "")
            if not rid:
                continue
            item = dict(region)
            item["page_number"] = pn
            out[rid] = item
    return out


def detached_region_provenance_is_source_only(region: dict[str, Any]) -> bool:
    region_type = str(region.get("region_type") or "").strip().lower()
    if region_type in {"", "text", "table", "native_residual"}:
        return False
    refs = [str(x) for x in (region.get("source_refs") or [])]
    return any(
        ref.startswith("stage1:image:")
        or ref.startswith("stage1:vector:")
        or ref.startswith("stage4:degenerate:")
        for ref in refs
    ) and not any(ref.startswith("stage4:block:") for ref in refs)


def visible_text_signature(record: dict[str, Any]) -> tuple[Any, ...]:
    """Fields that Stage10.1 must not mutate for native paragraph authority."""
    return (
        record.get("record_type"),
        record.get("text"),
        record.get("logical_paragraph_id"),
        tuple(record_pages(record)),
        record.get("section_id"),
        record.get("flow_role"),
        record.get("column_role"),
        record.get("reading_order"),
        record.get("page_flow_order"),
        record.get("effective_visibility"),
    )


def audit(native: dict[str, Any], qg: dict[str, Any], canonical: dict[str, Any], manifest: dict[str, Any], *, markdown: str | None = None) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []

    source_files = {
        str(native.get("source_file") or ""),
        str(qg.get("source_file") or ""),
        str(canonical.get("source_file") or ""),
        str(manifest.get("source_file") or ""),
    }
    source_files.discard("")
    if len(source_files) != 1:
        errors.append(f"source_file mismatch: {sorted(source_files)}")

    native_records = [x for x in native.get("records", []) if isinstance(x, dict)]
    canonical_records = [x for x in canonical.get("records", []) if isinstance(x, dict)]
    native_ids = [str(x.get("record_id") or "") for x in native_records]
    canonical_ids_raw = [str(x.get("record_id") or "") for x in canonical_records]

    native_by_id = {str(x.get("record_id")): x for x in native_records}
    canonical_by_id = {str(x.get("record_id")): x for x in canonical_records}

    # 1. Exact backbone preservation in Stage10.1.
    backbone_exact = native_ids == canonical_ids_raw
    if not backbone_exact:
        errors.append("Stage10.1 canonical record IDs/order differ from Stage6 native backbone")

    changed_base_records = [
        rid for rid in native_ids
        if rid not in canonical_by_id or {
            key: value for key, value in canonical_by_id[rid].items()
            if key not in {"stage10_record_index", "stage10_resolution"}
        } != native_by_id[rid]
    ]
    if changed_base_records:
        errors.append(f"Stage10.1 changed {len(changed_base_records)} Stage6 base records")

    section_backbone_exact = canonical.get("sections") == native.get("sections")
    if not section_backbone_exact:
        errors.append("Stage10.1 canonical sections differ from Stage6 native sections")

    corder = canonical_order(canonical)
    canonical_semantic_order_matches_native = corder == native_ids
    if not canonical_semantic_order_matches_native:
        errors.append("Stage10.1 section/record semantic order differs from Stage6 record order")

    # 2. Native paragraph authority unchanged in canonical.
    paragraph_ids = [rid for rid in native_ids if native_by_id[rid].get("record_type") == "paragraph"]
    changed_paragraphs: list[str] = []
    for rid in paragraph_ids:
        c = canonical_by_id.get(rid)
        if c is None or visible_text_signature(native_by_id[rid]) != visible_text_signature(c):
            changed_paragraphs.append(rid)
    if changed_paragraphs:
        errors.append(f"Stage10.1 changed {len(changed_paragraphs)} native paragraph authority records")

    decisions = qg_page_decisions(qg)
    native_route_pages = sorted(p for p, d in decisions.items() if d in {"NATIVE_PASS", "NATIVE_PASS_WITH_NON_TEXT"})
    strict_native_pages = sorted(p for p, d in decisions.items() if d == "NATIVE_PASS")
    native_with_non_text_pages = sorted(p for p, d in decisions.items() if d == "NATIVE_PASS_WITH_NON_TEXT")
    ocr_pages = sorted(p for p, d in decisions.items() if d == "OCR_REQUIRED")
    layout_pages = sorted(p for p, d in decisions.items() if d == "LAYOUT_FALLBACK_REQUIRED")

    # Actual Stage10.2 processing order is preserved by record_dispositions insertion order.
    dispositions = manifest.get("record_dispositions") or {}
    if not isinstance(dispositions, dict):
        dispositions = {}
    processed_ids = list(dispositions.keys())
    processed_pos = {rid: i for i, rid in enumerate(processed_ids)}

    allowed_para_dispositions = {
        "RENDERED_NATIVE_PARAGRAPH",
        "SUPPRESSED_BY_INLINE_CONTEXT_REPLACEMENT",
        "SUPPRESSED_BY_CANONICAL_VISIBILITY",
        "SUPPRESSED_DUPLICATE_SECTION_HEADING",
        "EMPTY_NATIVE_PARAGRAPH_SKIPPED",
    }

    native_page_paragraph_ids: list[str] = []
    paragraph_disp_counts = Counter()
    unexpected_para_dispositions: list[dict[str, Any]] = []
    for rid in paragraph_ids:
        r = native_by_id[rid]
        pages = record_pages(r)
        if not any(p in native_route_pages for p in pages):
            continue
        native_page_paragraph_ids.append(rid)
        disp = str((dispositions.get(rid) or {}).get("disposition") or "MISSING")
        paragraph_disp_counts[disp] += 1
        if disp not in allowed_para_dispositions:
            unexpected_para_dispositions.append({"record_id": rid, "pages": pages, "disposition": disp})
    if unexpected_para_dispositions:
        errors.append(f"Unexpected Stage10.2 disposition on {len(unexpected_para_dispositions)} native-route paragraphs")

    # Relative order of all native-route paragraph records as actually processed by renderer.
    expected_para_order = [rid for rid in native_ids if rid in set(native_page_paragraph_ids)]
    actual_para_order = sorted(
        [rid for rid in expected_para_order if rid in processed_pos],
        key=lambda rid: processed_pos[rid],
    )
    paragraph_relative_order_preserved = actual_para_order == expected_para_order
    if not paragraph_relative_order_preserved:
        errors.append("Stage10.2 processed native-route paragraphs in a different relative order")

    # 3. REGION must stay on the original Stage6 non-text visual anchor.
    # Stage7/8 NON_TEXT_UNASSESSED evidence can be image or vector. A materialized
    # table_ref is deliberately excluded: region OCR must never replace an already
    # materialized native table. Future unknown visual refs are accepted only when
    # they remain *_ref and preserve the exact Stage6 record type/id.
    region_modes = {"REGION_TEXT_ENRICHMENT", "REGION_PRESERVED_UNRESOLVED"}
    region_records = [
        r for r in canonical_records
        if str((r.get("stage10_resolution") or {}).get("mode") or "") in region_modes
    ]

    def is_region_visual_ref_type(record_type: Any) -> bool:
        value = str(record_type or "")
        return value.endswith("_ref") and value != "table_ref"

    bad_region_types: list[str] = []
    bad_region_position: list[str] = []
    region_record_type_counts: Counter[str] = Counter()
    for r in region_records:
        rid = str(r.get("record_id"))
        rtype = str(r.get("record_type") or "")
        region_record_type_counts[rtype] += 1
        if not is_region_visual_ref_type(rtype):
            bad_region_types.append(rid)
        nr = native_by_id.get(rid)
        if (
            nr is None
            or str(nr.get("record_type") or "") != rtype
            or not is_region_visual_ref_type(nr.get("record_type"))
        ):
            bad_region_position.append(rid)
    if bad_region_types:
        errors.append(f"REGION fallback attached to invalid non-text records: {bad_region_types[:8]}")
    if bad_region_position:
        errors.append(f"REGION fallback lost original Stage6 non-text anchor/type: {bad_region_position[:8]}")

    # Check REGION processing positions preserve surrounding canonical/native order.
    region_processing_order_ok = True
    native_pos = {rid: i for i, rid in enumerate(native_ids)}
    region_ids = [str(r.get("record_id")) for r in region_records]
    if [native_pos[rid] for rid in region_ids if rid in native_pos] != sorted(native_pos[rid] for rid in region_ids if rid in native_pos):
        region_processing_order_ok = False
        errors.append("REGION anchors are not monotonic in Stage6 native record order")

    # REGION tasks can also originate from Stage7 source-only visual evidence that never
    # became a Stage6 native record (for example stage1_unrepresented_image). Those
    # overlays must remain detached instead of being force-mapped to an unrelated ref.
    region_overlays = [
        x for x in ((canonical.get("fallback_overlays") or {}).get("region_fallbacks") or [])
        if isinstance(x, dict)
    ]
    detached_region_overlays = [x for x in region_overlays if not x.get("source_native_record_id")]
    qg_regions = qg_region_index(qg)
    detached_region_issues: list[dict[str, Any]] = []
    detached_manifest = manifest.get("detached_region_overlay_dispositions") or {}
    if not isinstance(detached_manifest, dict):
        detached_manifest = {}

    for ov in detached_region_overlays:
        source_id = str(ov.get("source_id") or "")
        tid = str(ov.get("task_id") or "")
        qgr = qg_regions.get(source_id) or {}
        reasons: list[str] = []
        if str(ov.get("anchor_status") or "") != "DETACHED_SOURCE_REGION_NOT_IN_STAGE6_FLOW":
            reasons.append("unexpected anchor_status")
        if not qgr:
            reasons.append("source region missing from Stage8")
        else:
            if str(qgr.get("action") or "") != "REGION_FALLBACK_REQUIRED":
                reasons.append("Stage8 action is not REGION_FALLBACK_REQUIRED")
            if not detached_region_provenance_is_source_only(qgr):
                reasons.append("region provenance does not prove source-only/unmaterialized evidence")
            try:
                if int(qgr.get("page_number")) != int(ov.get("page_number")):
                    reasons.append("page mismatch")
            except Exception:
                reasons.append("invalid page number")
        if tid not in detached_manifest:
            reasons.append("Stage10.2 did not account/render detached overlay")
        if reasons:
            detached_region_issues.append({
                "task_id": tid,
                "source_id": source_id,
                "reasons": reasons,
            })

    expected_region_overlay_count = int((canonical.get("summary") or {}).get("region_fallback_count", len(region_overlays)))
    if len(region_overlays) != expected_region_overlay_count:
        errors.append(
            f"REGION overlay count mismatch: overlays={len(region_overlays)} expected={expected_region_overlay_count}"
        )
    if len(region_records) + len(detached_region_overlays) != len(region_overlays):
        errors.append(
            "REGION accounting does not close across anchored records + detached overlays"
        )
    if detached_region_issues:
        errors.append(f"Detached REGION provenance/render issues: {len(detached_region_issues)}")

    # 4. INLINE locality and suppression boundary.
    inline_overlays = ((canonical.get("fallback_overlays") or {}).get("inline_contexts") or [])
    inline_overlay_issues: list[dict[str, Any]] = []
    inline_full_ids: set[str] = set()
    inline_partial_ids: set[str] = set()
    for ov in inline_overlays:
        if not isinstance(ov, dict):
            continue
        page = int(ov.get("page_number"))
        full = {str(x) for x in (ov.get("fully_contained_native_record_ids") or [])}
        partial = {str(x) for x in (ov.get("partially_overlapping_native_record_ids") or [])}
        inline_full_ids |= full
        inline_partial_ids |= partial

        overlap_ids = {
            str(x.get("record_id"))
            for x in (ov.get("overlap_diagnostics") or [])
            if isinstance(x, dict) and x.get("record_id")
        }
        if not full.issubset(overlap_ids) or not partial.issubset(overlap_ids):
            inline_overlay_issues.append({"task_id": ov.get("task_id"), "reason": "inline IDs not backed by overlap_diagnostics"})
        for rid in full | partial:
            r = native_by_id.get(rid)
            if r is None:
                inline_overlay_issues.append({"task_id": ov.get("task_id"), "record_id": rid, "reason": "inline target missing from Stage6"})
                continue
            if page not in record_pages(r):
                inline_overlay_issues.append({"task_id": ov.get("task_id"), "record_id": rid, "reason": "inline target crosses outside overlay page"})

    # Actual renderer may suppress full IDs, but must never suppress partial IDs by inline replacement.
    inline_suppressed_ids = {
        rid for rid, d in dispositions.items()
        if isinstance(d, dict) and d.get("disposition") == "SUPPRESSED_BY_INLINE_CONTEXT_REPLACEMENT"
    }
    if not inline_suppressed_ids.issubset(inline_full_ids):
        extra = sorted(inline_suppressed_ids - inline_full_ids)
        errors.append(f"INLINE renderer suppressed records not fully contained by context: {extra[:8]}")
    partial_wrongly_suppressed = sorted(inline_partial_ids & inline_suppressed_ids)
    if partial_wrongly_suppressed:
        errors.append(f"INLINE renderer suppressed partial-overlap native records: {partial_wrongly_suppressed[:8]}")
    if inline_overlay_issues:
        errors.append(f"INLINE locality issues: {len(inline_overlay_issues)}")

    # 5. PAGE OCR/layout fallback semantics must stay separate.
    page_ocr_records = [
        r for r in canonical_records
        if str((r.get("stage10_resolution") or {}).get("mode") or "") == "PAGE_FALLBACK_SOURCE"
    ]
    page_layout_records = [
        r for r in canonical_records
        if str((r.get("stage10_resolution") or {}).get("mode") or "") == "PAGE_LAYOUT_FALLBACK_SOURCE"
    ]

    page_ocr_fallback_pages = sorted({p for r in page_ocr_records for p in record_pages(r)})
    page_layout_fallback_pages = sorted({p for r in page_layout_records for p in record_pages(r)})

    page_ocr_set_exact = page_ocr_fallback_pages == ocr_pages
    if not page_ocr_set_exact:
        errors.append(
            f"PAGE OCR fallback pages != OCR_REQUIRED pages: "
            f"page_fallback={page_ocr_fallback_pages}, ocr_required={ocr_pages}"
        )

    page_layout_set_exact = page_layout_fallback_pages == layout_pages
    if not page_layout_set_exact:
        errors.append(
            f"PAGE layout fallback pages != LAYOUT_FALLBACK_REQUIRED pages: "
            f"page_layout={page_layout_fallback_pages}, layout_required={layout_pages}"
        )

    # Full-page fallback is page-authoritative: the physical PDF page is the boundary/anchor.
    # Stage6 is only the native logical-flow backbone and is NOT required to contain an image_ref
    # for every scan-like/OCR_REQUIRED page. A scanned page can legitimately materialize as
    # table_ref/paragraph records (or other page-local records) after Stage4~6 structure recovery.
    # Therefore the safe invariant is:
    #   1) PAGE OCR fallback page set exactly equals Stage8 OCR_REQUIRED;
    #   2) records superseded by that page result are page-local only.
    # Layout fallback follows the same page-locality rule because the native reading order/
    # structure itself is what Stage8 rejected.
    bad_ocr_cross_page_records = [
        str(r.get("record_id"))
        for r in page_ocr_records
        if len(record_pages(r)) != 1
    ]
    if bad_ocr_cross_page_records:
        errors.append(
            "PAGE OCR fallback must not fully supersede cross-page native records: "
            f"{bad_ocr_cross_page_records[:8]}"
        )

    # Diagnostic only: some OCR_REQUIRED pages may have a Stage6 image_ref, others may not.
    # Absence of image_ref is not a boundary failure because PAGE fallback is anchored by the
    # physical page number, not by a particular Stage6 visual record.
    ocr_image_anchor_pages = sorted({
        p
        for r in page_ocr_records
        if r.get("record_type") == "image_ref"
        for p in record_pages(r)
    })
    ocr_pages_without_stage6_image_ref = sorted(
        set(ocr_pages) - set(ocr_image_anchor_pages)
    )
    page_ocr_physical_page_boundary_ok = page_ocr_set_exact and not bad_ocr_cross_page_records

    bad_layout_cross_page_records = [
        str(r.get("record_id"))
        for r in page_layout_records
        if len(record_pages(r)) != 1
    ]
    if bad_layout_cross_page_records:
        errors.append(
            "PAGE layout fallback must not fully supersede cross-page native records: "
            f"{bad_layout_cross_page_records[:8]}"
        )

    page_nonocr = sorted(set(page_ocr_fallback_pages) - set(ocr_pages))
    missing_ocr = sorted(set(ocr_pages) - set(page_ocr_fallback_pages))
    page_nonlayout = sorted(set(page_layout_fallback_pages) - set(layout_pages))
    missing_layout = sorted(set(layout_pages) - set(page_layout_fallback_pages))

    # 6. Paragraph resolution modes are allowed to become non-NATIVE only when a full-page
    # fallback legitimately supersedes that page. This is expected for page-local text-layer
    # paragraphs on OCR_REQUIRED pages and for native paragraphs on LAYOUT_FALLBACK_REQUIRED
    # pages. Anything else remains an audit error.
    paragraph_modes = Counter()
    paragraph_fallback_mutations: list[dict[str, Any]] = []
    unexpected_paragraph_resolution_records: list[dict[str, Any]] = []
    for r in canonical_records:
        if r.get("record_type") != "paragraph":
            continue
        mode = str((r.get("stage10_resolution") or {}).get("mode") or "")
        pages = record_pages(r)
        paragraph_modes[mode] += 1
        if mode in {"", "NATIVE"}:
            continue

        item = {
            "record_id": r.get("record_id"),
            "pages": pages,
            "mode": mode,
        }
        paragraph_fallback_mutations.append(item)

        expected = False
        if len(pages) == 1:
            page = pages[0]
            if mode == "PAGE_FALLBACK_SOURCE" and page in ocr_pages:
                expected = True
            elif mode == "PAGE_LAYOUT_FALLBACK_SOURCE" and page in layout_pages:
                expected = True

        if not expected:
            unexpected_paragraph_resolution_records.append(item)

    if unexpected_paragraph_resolution_records:
        errors.append(
            "Paragraph carries non-NATIVE resolution outside matching Stage8 full-page fallback: "
            f"{unexpected_paragraph_resolution_records[:8]}"
        )

    document_unit_audit = audit_document_units(canonical, markdown)
    errors.extend(document_unit_audit["errors"])

    result = {
        "stage": STAGE,
        "version": VERSION,
        "source_file": next(iter(source_files)) if len(source_files) == 1 else None,
        "status": "PASS" if not errors else "FAIL",
        "ground_truth_used": False,
        "summary": {
            "stage6_record_count": len(native_records),
            "canonical_record_count": len(canonical_records),
            "changed_stage6_base_record_count": len(changed_base_records),
            "stage6_paragraph_count": len(paragraph_ids),
            "native_route_page_count": len(native_route_pages),
            "strict_native_page_count": len(strict_native_pages),
            "native_with_non_text_page_count": len(native_with_non_text_pages),
            "ocr_required_page_count": len(ocr_pages),
            "layout_fallback_required_page_count": len(layout_pages),
            "native_route_paragraph_count": len(native_page_paragraph_ids),
            "region_fallback_record_count": len(region_records),
            "region_fallback_overlay_count": len(region_overlays),
            "detached_region_fallback_count": len(detached_region_overlays),
            "region_fallback_record_type_counts": dict(region_record_type_counts),
            "inline_context_count": len(inline_overlays),
            "inline_full_contained_record_count": len(inline_full_ids),
            "inline_partial_overlap_record_count": len(inline_partial_ids),
            "inline_renderer_suppressed_record_count": len(inline_suppressed_ids),
            "page_fallback_record_count": len(page_ocr_records) + len(page_layout_records),
            "page_ocr_fallback_record_count": len(page_ocr_records),
            "page_ocr_image_anchor_page_count": len(ocr_image_anchor_pages),
            "page_ocr_without_stage6_image_ref_page_count": len(ocr_pages_without_stage6_image_ref),
            "page_layout_fallback_record_count": len(page_layout_records),
            "document_unit_count": document_unit_audit["units"],
            "document_unit_marker_count": document_unit_audit["rendered_markers"],
        },
        "checks": {
            "canonical_backbone_exact_stage6_ids_and_order": backbone_exact,
            "canonical_base_records_exact_stage6": not changed_base_records,
            "canonical_sections_exact_stage6": section_backbone_exact,
            "canonical_semantic_order_matches_stage6": canonical_semantic_order_matches_native,
            "canonical_native_paragraph_authority_unchanged": len(changed_paragraphs) == 0,
            "stage10_2_native_paragraph_relative_order_preserved": paragraph_relative_order_preserved,
            "region_only_on_original_non_text_anchors": not bad_region_types and not bad_region_position,
            # Backward-compatible alias; semantic name above is authoritative from v0.1.3.
            "region_only_on_original_image_ref_anchors": not bad_region_types and not bad_region_position,
            "region_anchor_order_monotonic": region_processing_order_ok,
            "detached_region_overlays_are_source_only_and_rendered": not detached_region_issues,
            "region_accounting_closes_anchored_plus_detached": len(region_records) + len(detached_region_overlays) == len(region_overlays),
            "inline_suppression_subset_of_fully_contained": inline_suppressed_ids.issubset(inline_full_ids),
            "inline_partial_overlap_not_suppressed": not partial_wrongly_suppressed,
            "inline_targets_page_local_and_overlap_backed": not inline_overlay_issues,
            "page_ocr_fallback_pages_exactly_match_ocr_required": page_ocr_set_exact,
            "page_ocr_fallback_sources_are_page_local": not bad_ocr_cross_page_records,
            "page_ocr_fallback_uses_physical_page_boundary": page_ocr_physical_page_boundary_ok,
            "page_layout_fallback_pages_exactly_match_layout_required": page_layout_set_exact,
            "page_layout_fallback_sources_are_page_local": not bad_layout_cross_page_records,
            "page_fallback_paragraph_modes_match_stage8_decision": not unexpected_paragraph_resolution_records,
            "no_unexpected_native_route_paragraph_disposition": not unexpected_para_dispositions,
        },
        "native_route": {
            "pages": native_route_pages,
            "strict_native_pages": strict_native_pages,
            "native_with_non_text_pages": native_with_non_text_pages,
            "paragraph_disposition_counts": dict(paragraph_disp_counts),
            "unexpected_paragraph_dispositions": unexpected_para_dispositions,
            "changed_native_paragraph_record_ids": changed_paragraphs,
        },
        "region": {
            "record_ids": region_ids,
            "record_type_counts": dict(region_record_type_counts),
            "bad_invalid_non_text_record_ids": bad_region_types,
            "bad_missing_or_type_changed_stage6_anchor_record_ids": bad_region_position,
            "overlay_count": len(region_overlays),
            "detached_overlay_count": len(detached_region_overlays),
            "detached_overlay_issues": detached_region_issues,
        },
        "inline": {
            "fully_contained_record_ids": sorted(inline_full_ids, key=lambda rid: native_pos.get(rid, 10**9)),
            "partially_overlapping_record_ids": sorted(inline_partial_ids, key=lambda rid: native_pos.get(rid, 10**9)),
            "renderer_suppressed_record_ids": sorted(inline_suppressed_ids, key=lambda rid: native_pos.get(rid, 10**9)),
            "partial_wrongly_suppressed_record_ids": partial_wrongly_suppressed,
            "overlay_issues": inline_overlay_issues,
        },
        "page_fallback": {
            "ocr_required_pages": ocr_pages,
            "layout_fallback_required_pages": layout_pages,
            "page_ocr_fallback_pages": page_ocr_fallback_pages,
            "page_layout_fallback_pages": page_layout_fallback_pages,
            "unexpected_non_ocr_pages": page_nonocr,
            "missing_ocr_required_pages": missing_ocr,
            "unexpected_non_layout_pages": page_nonlayout,
            "missing_layout_required_pages": missing_layout,
            "bad_ocr_cross_page_record_ids": bad_ocr_cross_page_records,
            "ocr_image_anchor_pages": ocr_image_anchor_pages,
            "ocr_pages_without_stage6_image_ref": ocr_pages_without_stage6_image_ref,
            "bad_layout_cross_page_record_ids": bad_layout_cross_page_records,
        },
        "paragraph_resolution_mode_counts": dict(paragraph_modes),
        "paragraph_non_native_resolution_records": paragraph_fallback_mutations,
        "unexpected_paragraph_resolution_records": unexpected_paragraph_resolution_records,
        "document_unit_audit": document_unit_audit,
        "validation": {
            "pass": not errors,
            "errors": errors,
            "warnings": warnings,
        },
    }
    return result


def render_md(result: dict[str, Any]) -> str:
    s = result["summary"]
    c = result["checks"]
    n = result["native_route"]
    lines = [
        "# Stage 10.2.1 Structure Boundary Audit",
        "",
        f"- Source: `{result.get('source_file')}`",
        f"- Status: **{result.get('status')}**",
        "- Ground Truth used: `False`",
        "",
        "## Core invariants",
        "",
    ]
    labels = {
        "canonical_backbone_exact_stage6_ids_and_order": "Stage10.1 canonical keeps exact Stage6 record IDs/order",
        "canonical_base_records_exact_stage6": "Stage10.1 canonical keeps exact Stage6 base record fields",
        "canonical_sections_exact_stage6": "Stage10.1 canonical keeps exact Stage6 sections",
        "canonical_semantic_order_matches_stage6": "Canonical section semantic order matches Stage6",
        "canonical_native_paragraph_authority_unchanged": "Native paragraph text/provenance unchanged in canonical",
        "stage10_2_native_paragraph_relative_order_preserved": "Stage10.2 preserves native paragraph relative order",
        "region_only_on_original_non_text_anchors": "REGION fallback stays on original non-text visual anchors (image/vector)",
        "region_anchor_order_monotonic": "REGION anchors remain monotonic in Stage6 order",
        "detached_region_overlays_are_source_only_and_rendered": "Detached REGION overlays are proven source-only evidence and rendered explicitly",
        "region_accounting_closes_anchored_plus_detached": "REGION accounting closes across anchored records plus detached overlays",
        "inline_suppression_subset_of_fully_contained": "INLINE suppresses only fully-contained native records",
        "inline_partial_overlap_not_suppressed": "INLINE partial-overlap native records remain unsuppressed",
        "inline_targets_page_local_and_overlap_backed": "INLINE targets are page-local and overlap-backed",
        "page_ocr_fallback_pages_exactly_match_ocr_required": "PAGE OCR fallback pages exactly equal Stage8 OCR_REQUIRED pages",
        "page_ocr_fallback_sources_are_page_local": "PAGE OCR fallback supersedes only page-local Stage6 records",
        "page_ocr_fallback_uses_physical_page_boundary": "PAGE OCR fallback is bounded by the physical page; Stage6 image_ref is not required",
        "page_layout_fallback_pages_exactly_match_layout_required": "PAGE layout fallback pages exactly equal Stage8 LAYOUT_FALLBACK_REQUIRED pages",
        "page_layout_fallback_sources_are_page_local": "PAGE layout fallback supersedes only page-local Stage6 records",
        "page_fallback_paragraph_modes_match_stage8_decision": "Non-NATIVE paragraph modes occur only on matching full-page fallback pages",
        "no_unexpected_native_route_paragraph_disposition": "No unexpected Stage10.2 disposition on native-route paragraphs",
    }
    for key, label in labels.items():
        lines.append(f"- {'PASS' if c.get(key) else 'FAIL'} — {label}")

    lines += [
        "",
        "## Counts",
        "",
        f"- Stage6 records: {s['stage6_record_count']}",
        f"- Canonical records: {s['canonical_record_count']}",
        f"- Stage6 paragraphs: {s['stage6_paragraph_count']}",
        f"- Native-route pages: {s['native_route_page_count']} (NATIVE_PASS={s['strict_native_page_count']}, NATIVE_PASS_WITH_NON_TEXT={s['native_with_non_text_page_count']})",
        f"- Native-route paragraphs: {s['native_route_paragraph_count']}",
        f"- REGION fallback overlays: {s['region_fallback_overlay_count']} | anchored records={s['region_fallback_record_count']} | detached={s['detached_region_fallback_count']}",
        f"- INLINE contexts: {s['inline_context_count']} | full-contained records={s['inline_full_contained_record_count']} | partial-overlap records={s['inline_partial_overlap_record_count']} | renderer-suppressed={s['inline_renderer_suppressed_record_count']}",
        f"- OCR_REQUIRED pages: {s['ocr_required_page_count']} | PAGE OCR fallback records={s['page_ocr_fallback_record_count']} | without Stage6 image_ref={s['page_ocr_without_stage6_image_ref_page_count']}",
        f"- LAYOUT_FALLBACK_REQUIRED pages: {s['layout_fallback_required_page_count']} | PAGE layout fallback records={s['page_layout_fallback_record_count']}",
        f"- DocumentUnits: {s['document_unit_count']} | boundary markers={s['document_unit_marker_count']} | semantic audit={result['document_unit_audit']['status']}",
        "",
        "## Native paragraph dispositions",
        "",
    ]
    for key, value in sorted(n["paragraph_disposition_counts"].items()):
        lines.append(f"- `{key}`: {value}")

    if result["validation"]["errors"]:
        lines += ["", "## Errors", ""]
        for x in result["validation"]["errors"]:
            lines.append(f"- {x}")
    if result["validation"]["warnings"]:
        lines += ["", "## Warnings", ""]
        for x in result["validation"]["warnings"]:
            lines.append(f"- {x}")

    lines += [
        "",
        "## Interpretation",
        "",
        "A PASS means the Stage9/10 merge layer is structurally behaving as an overlay/replacement layer: native Stage6 record order is retained, REGION stays on original Stage6 visual anchors when available, Stage7 source-only visuals remain explicit detached overlays, INLINE changes are bounded to overlap-defined local contexts, and whole-page replacement is limited to the matching Stage8 OCR/layout fallback pages, with the physical page itself serving as the PAGE fallback boundary.",
        "",
        "This audit does **not** claim that Stage6 native text itself is semantically correct, and it does **not** score OCR usefulness/quality. Those are separate quality checks.",
        "",
    ]
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Stage10.2.1 Stage6→AI-read structural boundary audit")
    p.add_argument("--native-flow", required=True)
    p.add_argument("--quality-gate", required=True)
    p.add_argument("--canonical", required=True)
    p.add_argument("--render-manifest", required=True)
    p.add_argument("--markdown", help="Rendered Markdown; defaults to the path declared by render manifest")
    p.add_argument("--output", required=True)
    return p.parse_args()


def main() -> int:
    a = parse_args()
    out = Path(a.output)
    out.mkdir(parents=True, exist_ok=True)
    manifest = load_json(Path(a.render_manifest))
    markdown_path = a.markdown or (manifest.get("outputs") or {}).get("llm_ready_markdown")
    markdown = Path(markdown_path).read_text(encoding="utf-8") if markdown_path and Path(markdown_path).is_file() else None
    result = audit(
        load_json(Path(a.native_flow)),
        load_json(Path(a.quality_gate)),
        load_json(Path(a.canonical)),
        manifest,
        markdown=markdown,
    )
    (out / "structure_boundary_audit.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "structure_boundary_audit.md").write_text(render_md(result), encoding="utf-8")

    print("=" * 112)
    print(f"Stage {STAGE} Structure Boundary Audit | version={VERSION} | source={result.get('source_file')}")
    print("=" * 112)
    s = result["summary"]
    c = result["checks"]
    print(f"Stage6 records      | {s['stage6_record_count']}")
    print(f"Canonical records   | {s['canonical_record_count']}")
    print(f"Native route pages  | {s['native_route_page_count']} = PASS:{s['strict_native_page_count']} + PASS_WITH_NON_TEXT:{s['native_with_non_text_page_count']}")
    print(f"Native paragraphs   | {s['native_route_paragraph_count']}")
    print(f"REGION              | overlays={s['region_fallback_overlay_count']} anchored={s['region_fallback_record_count']} detached={s['detached_region_fallback_count']}")
    print(f"INLINE              | {s['inline_context_count']} contexts | full={s['inline_full_contained_record_count']} partial={s['inline_partial_overlap_record_count']} suppressed={s['inline_renderer_suppressed_record_count']}")
    print(f"PAGE fallback       | {s['page_fallback_record_count']} | OCR_REQUIRED={s['ocr_required_page_count']} | LAYOUT_REQUIRED={s['layout_fallback_required_page_count']}")
    print(f"Backbone exact      | {'PASS' if c['canonical_backbone_exact_stage6_ids_and_order'] else 'FAIL'}")
    print(f"Native text stable  | {'PASS' if c['canonical_native_paragraph_authority_unchanged'] else 'FAIL'}")
    print(f"Native order stable | {'PASS' if c['stage10_2_native_paragraph_relative_order_preserved'] else 'FAIL'}")
    print(f"REGION boundary     | {'PASS' if c['region_only_on_original_non_text_anchors'] and c['detached_region_overlays_are_source_only_and_rendered'] and c['region_accounting_closes_anchored_plus_detached'] else 'FAIL'}")
    print(f"INLINE boundary     | {'PASS' if c['inline_suppression_subset_of_fully_contained'] and c['inline_partial_overlap_not_suppressed'] and c['inline_targets_page_local_and_overlap_backed'] else 'FAIL'}")
    print(
        f"PAGE boundary       | "
        f"{'PASS' if c['page_ocr_fallback_pages_exactly_match_ocr_required'] and c['page_ocr_fallback_sources_are_page_local'] and c['page_ocr_fallback_uses_physical_page_boundary'] and c['page_layout_fallback_pages_exactly_match_layout_required'] and c['page_layout_fallback_sources_are_page_local'] and c['page_fallback_paragraph_modes_match_stage8_decision'] else 'FAIL'}"
    )
    print(f"Validation          | {'PASS' if result['validation']['pass'] else 'FAIL'}")
    if result["validation"]["errors"]:
        for e in result["validation"]["errors"]:
            print(f"  ERROR: {e}")
    if result["validation"]["warnings"]:
        for w in result["validation"]["warnings"]:
            print(f"  WARN : {w}")
    print(f"JSON                | {out / 'structure_boundary_audit.json'}")
    print(f"Markdown            | {out / 'structure_boundary_audit.md'}")
    print("=" * 112)
    return 0 if result["validation"]["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
