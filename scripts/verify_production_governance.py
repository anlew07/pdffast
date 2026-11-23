"""Run isolated production acceptance and emit only sanitized lifecycle evidence."""

from __future__ import annotations

import argparse
import json
import resource
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

from pdffast import ParserConfig, PDFFastParser, preflight_production_profile
from pdffast.application.input_fingerprint import fingerprint_input
from pdffast.application.production_preflight import preflight_snapshot
from pdffast.application.production_profile import load_production_profile
from pdffast.pipeline.artifacts import ArtifactPaths
from pdffast.providers.base import ProviderTask


def _emit(data: dict) -> None:
    print(json.dumps(data, ensure_ascii=False), flush=True)


def _stage(name: str, **fields) -> None:
    _emit({"pdffast_acceptance_event": name, **fields})


def _read(path: Path) -> dict:
    return json.loads(path.read_bytes()) if path.is_file() else {}


def _synthetic_native_pdf(path: Path) -> None:
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R 4 0 R] /Count 2 >>",
    ]
    for stream_id in (6, 7):
        objects.append(
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            b"/Resources << /Font << /F1 5 0 R >> >> /Contents " + str(stream_id).encode() + b" 0 R >>"
        )
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for page in (1, 2):
        lines = [f"Native research proposal page {page}"] + [
            f"Experiment {page}-{i} examines sensor sampling and edge reliability under load."
            for i in range(12)
        ]
        content = ("BT /F1 10 Tf 45 780 Td 30 TL "
                   + " T* ".join(f"({line}) Tj" for line in lines) + " ET").encode("ascii")
        objects.append(b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream")
    pdf = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, item in enumerate(objects, 1):
        offsets.append(len(pdf))
        pdf.extend(f"{number} 0 obj\n".encode() + item + b"\nendobj\n")
    xref = len(pdf)
    pdf.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    pdf.extend("".join(f"{offset:010d} 00000 n \n" for offset in offsets).encode())
    pdf.extend(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    with path.open("xb") as stream:
        stream.write(pdf)


def _child(args: argparse.Namespace) -> int:
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    _stage("child_started")
    config = ParserConfig(
        project_root=args.project_root, provider_profile=args.provider_profile,
        output_root=args.output_root, capture_output=False,
    )
    run_dir = args.output_root / args.run_id
    if args.native_only:
        source = run_dir.parent / f"{args.run_id}.pdf"
        _synthetic_native_pdf(source)
    else:
        source = args.pdf
    try:
        if args.provider:
            snapshot = load_production_profile(config)
            report = preflight_snapshot(snapshot, config)
            if report["status"] != "PASS":
                _stage("preflight_failed")
                return 3
            name = args.provider
            _stage("provider_identity_verified", effective_config_fingerprint=report["effective_config_fingerprint"])
            run_dir.mkdir(exist_ok=False)
            image = run_dir / "synthetic.png"
            from PIL import Image, ImageDraw, ImageFont

            crop = Image.new("RGB", (740, 220), "white")
            draw = ImageDraw.Draw(crop)
            font = ImageFont.load_default(size=42)
            draw.text((30, 24), "Experiment report", fill="black", font=font)
            draw.text((30, 93), "Sample 2026 - sensor test", fill="black", font=font)
            crop.save(image)
            provider = snapshot.registry.create(name, snapshot.configs[name])
            try:
                _stage("provider_preflight_started")
                if not provider.preflight().available:
                    return 3
                provider.initialize()
                _stage("provider_initialized")
                prediction = provider.execute(ProviderTask(
                    task_id="synthetic", capability_route="PAGE_DOCUMENT_OCR",
                    input_image=image, metadata={"raw_output_dir": str(run_dir)},
                ))
                _stage("provider_execute_returned", status=prediction.status,
                       nonempty=bool((prediction.markdown or prediction.payload.get("text") or "").strip()))
            finally:
                _stage("provider_close_started")
                provider.close()
                _stage("provider_close_returned")
            return 0
        _stage("parse_started")
        result = PDFFastParser(config=config).parse(source, run_id=args.run_id)
        status = result.parser_provenance["execution_status"]
        _stage("parse_returned", status=status)
        return 0 if status == "COMPLETED" else 3
    except Exception as exc:
        _stage("python_exception", status=getattr(exc, "status", "EXECUTION_FAILED"),
               error_type=type(exc).__name__, cause_type=type(exc.__cause__).__name__,
               worker_returncode=getattr(exc, "returncode", getattr(exc.__cause__, "returncode", None)))
        raise SystemExit(1) from exc


def summarize_parse(
    run_dir: Path, returncode: int, expected: dict, *, input_sha256: str | None,
) -> dict:
    paths = ArtifactPaths.for_run(run_dir.resolve())
    manifest = _read(paths.result.manifest_json)
    provenance = manifest.get("parser_provenance") or {}
    audit = _read(paths.result.audit_json)
    profile = _read(paths.native.profile)
    execution = _read(paths.observability.execution_plan)
    internal = _read(paths.providers.production_manifest)
    planned_routes: dict[str, int] = {}
    planned_names = set()
    for task in execution.get("tasks", []):
        route = task["capability_route"]
        planned_routes[route] = planned_routes.get(route, 0) + 1
        planned_names.update(candidate["provider"] for candidate in task["provider_chain"])
    summary = internal.get("summary", {})
    attempted = summary.get("attempt_provider_counts")
    selected = summary.get("selected_provider_counts")
    allowed = set(expected.get("allowed_providers", []))
    unexpected = (
        sum(value for name, value in attempted.items() if name not in allowed)
        if attempted is not None else None
    )
    document = _read(paths.result.document_json)
    markdown_written = paths.result.document_md.is_file()
    audit_passed = audit.get("validation", {}).get("pass")
    page_count = profile.get("page_count")
    outcome_fields = ("accepted_task_count", "terminal_preserve_count", "pipeline_failure_count")
    outcomes = [summary.get(key) for key in outcome_fields]
    planned = summary.get("task_count")
    input_matches = (
        input_sha256 is not None and manifest.get("input", {}).get("sha256") == input_sha256
    )
    ready = (
        returncode == 0 and bool(document) and markdown_written and audit_passed is True
        and bool(paths.result.document_md.read_text(encoding="utf-8").strip())
        and type(page_count) is int and page_count > 0
        and document.get("page_count") == page_count
        and isinstance(document.get("pages"), list) and len(document["pages"]) == page_count
        and manifest.get("run_id") == run_dir.name and input_matches
        and manifest.get("result") == {
            "document": str(paths.result.document_json), "markdown": str(paths.result.document_md),
            "audit": str(paths.result.audit_json),
        }
        and provenance.get("schema_version") == expected.get("schema_version") == "1.0"
        and type(planned) is int and planned == len(execution.get("tasks", []))
        and provenance.get("planned_task_count") == planned
        and provenance.get("provider_execution_required") is bool(planned)
        and all(type(value) is int and value >= 0 for value in outcomes)
        and sum(outcomes) == planned
        and all(provenance.get(key) == summary[key] for key in outcome_fields)
        and attempted == provenance.get("attempted_provider_counts")
        and isinstance(selected, dict) and selected == provenance.get("selected_provider_counts")
        and all(type(value) is int and value > 0 for value in selected.values())
        and sum(selected.values()) == summary["accepted_task_count"]
        and selected.keys() <= allowed
        and provenance.get("execution_status") == "COMPLETED"
        and provenance.get("profile_locked") is True
        and provenance.get("preflight_status") == "PASS"
        and provenance.get("outputs_written") is True
        and provenance.get("audit_passed") is True
        and provenance.get("pipeline_failure_count") == 0
        and expected.get("status") == "PASS"
        and all(provenance.get(key) == expected[key] for key in (
            "profile_name", "profile_sha256", "providers_config_sha256", "effective_config_fingerprint",
            "allowed_providers", "capability_routes", "pdffast_commit", "code_identity",
        ))
        and unexpected == 0 and planned_names <= allowed
    )
    return {
        "acceptance": "PASS" if ready else "FAIL", "page_count": page_count,
        "input_sha256_matched": input_matches,
        "profile_sha256": provenance.get("profile_sha256"),
        "effective_config_fingerprint": provenance.get("effective_config_fingerprint"),
        "execution_status": provenance.get("execution_status"),
        "planned_task_count": summary.get("task_count"), "planned_routes": planned_routes,
        "attempted_provider_counts": attempted, "selected_provider_counts": selected,
        "audit_passed": audit_passed, "markdown_written": markdown_written,
        "canonical_written": bool(document), "manifest_written": bool(manifest),
        "forbidden_attempt_count": unexpected,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--provider-profile", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--pdf", type=Path)
    mode.add_argument("--native-only", action="store_true")
    mode.add_argument("--provider")
    parser.add_argument("--run-id")
    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.child:
        return _child(args)

    args.output_root.mkdir(parents=True, exist_ok=True)
    run_id = args.run_id or f"governance-{uuid4().hex}"
    if not run_id or Path(run_id).name != run_id or run_id in {".", ".."}:
        parser.error("run-id must be a single directory name")
    run_dir = args.output_root / run_id
    if run_dir.exists() or run_dir.is_symlink():
        parser.error("run directory already exists")
    expected = preflight_production_profile(
        project_root=args.project_root, provider_profile=args.provider_profile,
    )
    if expected["status"] != "PASS":
        _emit({"acceptance": "BLOCKED", "preflight_status": expected["status"]})
        return 3
    if args.provider and args.provider not in expected["allowed_providers"]:
        parser.error("provider is not allowed by the profile")
    input_sha256 = fingerprint_input(args.pdf)["sha256"] if args.pdf is not None else None
    if args.pdf is not None and input_sha256 is None:
        _emit({"acceptance": "BLOCKED", "input_fingerprint_status": "FAILED"})
        return 3
    command = [sys.executable, "-B", "-m", "scripts.verify_production_governance"]
    command.extend(sys.argv[1:])
    if args.run_id is None:
        command.extend(["--run-id", run_id])
    command.append("--child")
    child = subprocess.run(command, capture_output=True, text=True, errors="replace", check=False)
    events = []
    for line in child.stdout.splitlines():
        try:
            event = json.loads(line)
            if isinstance(event, dict) and "pdffast_acceptance_event" in event:
                events.append(event)
        except json.JSONDecodeError:
            continue
    report = {
        "run_id": run_id, "returncode": child.returncode, "events": events,
        "recursive_mutex_abort_signature": "recursive_mutex lock failed" in child.stderr,
        "child_started": bool(events),
    }
    if args.provider:
        report["provider"] = args.provider
        identity_matches = any(
            event["pdffast_acceptance_event"] == "provider_identity_verified"
            and event.get("effective_config_fingerprint") == expected["effective_config_fingerprint"]
            for event in events
        )
        report["acceptance"] = "PASS" if child.returncode == 0 and identity_matches and any(
            event["pdffast_acceptance_event"] == "provider_execute_returned"
            and event["status"] in {"SUCCESS", "SUCCESS_WITH_WARNINGS"} and event["nonempty"]
            for event in events
        ) else "FAIL"
    else:
        if args.native_only:
            input_sha256 = fingerprint_input(run_dir.parent / f"{run_id}.pdf")["sha256"]
        report.update(summarize_parse(run_dir, child.returncode, expected, input_sha256=input_sha256))
        if args.native_only and report["planned_task_count"] != 0:
            report["acceptance"] = "FAIL"
        if args.pdf is not None:
            report.update(pdf_id=args.pdf.stem, pdf_sha256=input_sha256)
            if fingerprint_input(args.pdf)["sha256"] != input_sha256:
                report["input_sha256_matched"] = False
                report["acceptance"] = "FAIL"
    _emit(report)
    return 0 if report["acceptance"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
