"""Stdlib-only capture code embedded in the isolated, pinned MinerU Worker.

Capture the existing output callback's memory, never reopen raw sidecars.
"""
CAPTURE_CODE = r'''
import contextlib
import inspect

@contextlib.contextmanager
def capture_supplemental(common, physical_page, task_id):
    envelope = {"version": "1", "blocks": [], "diagnostics": [],
                "capture_status": "NOT_CALLED", "callback_count": 0}
    original = getattr(common, "_process_output", None)
    try:
        signature = inspect.signature(original)
    except (TypeError, ValueError):
        signature = None
    if signature is None or "pdf_info" not in signature.parameters:
        envelope["capture_status"] = "UNAVAILABLE"
        envelope["diagnostics"].append({"reason": "MINERU_CAPTURE_API_UNAVAILABLE"})
        yield envelope
        return
    if not isinstance(physical_page, int) or isinstance(physical_page, bool) or physical_page < 1:
        envelope["capture_status"] = "UNAVAILABLE"
        envelope["diagnostics"].append({"reason": "PHYSICAL_PAGE_UNAVAILABLE"})
        yield envelope
        return
    def captured(*args, **kwargs):
        # Call original export unchanged; failures still propagate.
        envelope["callback_count"] += 1
        try:
            result = original(*args, **kwargs)
        except BaseException:
            envelope["capture_status"] = "EXPORT_FAILED"
            raise
        try:
            pages = signature.bind(*args, **kwargs).arguments["pdf_info"]
            if len(pages) != 1:
                envelope["capture_status"] = "UNAVAILABLE"
                envelope["diagnostics"].append({"reason": "MULTIPAGE_MAPPING_UNAVAILABLE"})
                return result
            page = pages[0]
            discarded = page.get("discarded_blocks", [])
            envelope["raw_block_count"] = len(discarded)
            for position, block in enumerate(discarded):
                kind = block.get("type")
                source = "task:" + str(task_id) + "/page:0/discarded_blocks/" + str(position)
                if kind != "page_footnote":
                    envelope["diagnostics"].append({"source_id": source, "original_type": kind,
                        "reason": "EXCLUDED_ROLE" if kind in ("header", "footer", "page_number", "aside_text", "image") else "UNKNOWN_TYPE"})
                    continue
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        if span.get("type") not in ("text", "inline_equation", "interline_equation"):
                            envelope["diagnostics"].append({"source_id": source, "reason": "UNKNOWN_SPAN_TYPE", "span_type": span.get("type")})
                text = "\n".join(" ".join(str(span.get("content", ""))
                    for span in line.get("spans", []) if span.get("type") in ("text", "inline_equation", "interline_equation"))
                    for line in block.get("lines", [])).strip()
                envelope["blocks"].append({"original_type": kind, "text": text,
                    "page": physical_page, "bbox": block.get("bbox"), "page_size": page.get("page_size"),
                    "coordinate_system": "mineru_page", "unit": "pdf_point",
                    "source_id": source, "source_index": block.get("index"), "source_position": position})
            envelope["capture_status"] = "PARTIAL" if any(
                d["reason"] == "UNKNOWN_SPAN_TYPE" for d in envelope["diagnostics"]
            ) else "COMPLETE"
        except Exception as error:
            envelope["capture_status"] = "FAILED"
            envelope["diagnostics"].append({"reason": "SUPPLEMENTAL_CAPTURE_FAILED", "error": type(error).__name__ + ": " + str(error)})
        return result
    common._process_output = captured
    try:
        yield envelope
    finally:
        common._process_output = original
        if envelope["callback_count"] == 0:
            envelope["diagnostics"].append({"reason": "CAPTURE_NOT_CALLED"})
'''
