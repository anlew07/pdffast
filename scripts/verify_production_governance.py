"""Run isolated production acceptance and emit only sanitized lifecycle evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import resource
import stat
import subprocess
import sys
from collections import Counter
from pathlib import Path, PurePosixPath
from uuid import uuid4

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError as JSONSchemaSchemaError
from jsonschema.exceptions import ValidationError as JSONSchemaValidationError

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


def _contract_artifact_path(run_dir: Path, raw_path: str) -> Path:
    """Resolve one run-relative contract path without following symlinks."""
    if (
        not isinstance(raw_path, str) or not raw_path or "\\" in raw_path
        or "\\x00" in raw_path
    ):
        raise ValueError("invalid contract artifact path")
    relative = PurePosixPath(raw_path)
    if (
        relative.is_absolute() or relative.as_posix() != raw_path
        or not relative.parts or any(part in {"", ".", ".."} for part in relative.parts)
        or relative.parts[0].endswith(":")
    ):
        raise ValueError("contract artifact path is not normalized and relative")

    root = Path(run_dir).resolve(strict=True)
    candidate = root.joinpath(*relative.parts)
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("contract artifact path contains a symlink")
    resolved = candidate.resolve(strict=True)
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise ValueError("contract artifact path escapes the run directory")
    return resolved


def _read_run_relative_files(
    run_dir: Path,
    raw_paths: list[str],
    *,
    expected_root_identity: tuple[int, int] | None = None,
) -> tuple[dict[str, bytes], tuple[int, int]]:
    """Read run artifacts through pinned directory descriptors without following links."""
    original_root = Path(run_dir)
    if original_root.is_symlink():
        raise ValueError("run directory cannot be a symlink")
    root = original_root.resolve(strict=True)
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | nofollow
    file_flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | nofollow

    try:
        root_fd = os.open(root, directory_flags)
    except OSError as exc:
        raise ValueError("unable to safely open run directory") from exc

    payloads: dict[str, bytes] = {}
    try:
        root_stat = os.fstat(root_fd)
        if not stat.S_ISDIR(root_stat.st_mode):
            raise ValueError("run root is not a directory")
        root_identity = (root_stat.st_dev, root_stat.st_ino)
        if expected_root_identity is not None and root_identity != expected_root_identity:
            raise ValueError("run directory changed during verification")

        for raw_path in raw_paths:
            if not isinstance(raw_path, str) or not raw_path or chr(92) in raw_path or chr(0) in raw_path:
                raise ValueError("invalid run-relative artifact path")
            if raw_path in payloads:
                continue
            relative = PurePosixPath(raw_path)
            if (
                relative.is_absolute()
                or relative.as_posix() != raw_path
                or not relative.parts
                or any(part in {"", ".", ".."} for part in relative.parts)
                or relative.parts[0].endswith(":")
            ):
                raise ValueError("artifact path is not normalized and relative")

            parent_fd = os.dup(root_fd)
            try:
                for part in relative.parts[:-1]:
                    try:
                        next_fd = os.open(part, directory_flags, dir_fd=parent_fd)
                    except OSError as exc:
                        raise ValueError("artifact path contains an unsafe directory component") from exc
                    os.close(parent_fd)
                    parent_fd = next_fd

                file_fd = -1
                try:
                    try:
                        file_fd = os.open(relative.parts[-1], file_flags, dir_fd=parent_fd)
                    except OSError as exc:
                        raise ValueError("unable to safely open run artifact") from exc
                    with os.fdopen(file_fd, "rb") as stream:
                        file_fd = -1
                        before = os.fstat(stream.fileno())
                        if not stat.S_ISREG(before.st_mode):
                            raise ValueError("run artifact is not a regular file")
                        payload = stream.read()
                        after = os.fstat(stream.fileno())
                    before_identity = (
                        before.st_dev, before.st_ino, before.st_size,
                        before.st_mtime_ns, before.st_ctime_ns,
                    )
                    after_identity = (
                        after.st_dev, after.st_ino, after.st_size,
                        after.st_mtime_ns, after.st_ctime_ns,
                    )
                    if before_identity != after_identity or len(payload) != after.st_size:
                        raise ValueError("run artifact changed while being read")
                    payloads[raw_path] = payload
                finally:
                    if file_fd >= 0:
                        os.close(file_fd)
            finally:
                os.close(parent_fd)

        return payloads, root_identity
    finally:
        os.close(root_fd)


def _verify_execution_contract(
    run_dir: Path,
    *,
    manifest: dict,
    provenance: dict,
    expected: dict,
    input_sha256: str | None,
    audit: dict,
    execution_plan: dict,
    production_manifest: dict,
    selected_index: dict,
    artifact_bytes: dict[str, bytes] | None = None,
) -> bool:
    """Independently verify the published Embedded contract and its file hashes."""
    try:
        contract = manifest.get("execution_contract")
        if not isinstance(contract, dict):
            return False
        if (
            contract.get("schema_version") != "pdffast.execution.v1"
            or contract.get("run_id") != run_dir.name
            or manifest.get("run_id") != run_dir.name
        ):
            return False

        schema_path = (
            Path(__file__).resolve().parents[1]
            / "docs/contracts/embedded_execution.v1.schema.json"
        )
        schema = json.loads(schema_path.read_bytes())
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(contract)

        manifest_input = manifest.get("input") or {}
        contract_input = contract.get("input") or {}
        if (
            input_sha256 is None
            or contract_input.get("algorithm") != "sha256"
            or contract_input.get("status") != "COMPLETE"
            or contract_input.get("sha256") != input_sha256
            or manifest_input.get("sha256") != input_sha256
            or type(contract_input.get("byte_size")) is not int
            or contract_input.get("byte_size") < 1
            or contract_input.get("byte_size") != manifest_input.get("byte_size")
        ):
            return False

        result_paths = {
            "document": pathsafe(run_dir, ArtifactPaths.for_run(run_dir).result.document_json),
            "markdown": pathsafe(run_dir, ArtifactPaths.for_run(run_dir).result.document_md),
            "audit": pathsafe(run_dir, ArtifactPaths.for_run(run_dir).result.audit_json),
        }
        evidence_paths = {
            "production_manifest": pathsafe(
                run_dir, ArtifactPaths.for_run(run_dir).providers.production_manifest,
            ),
            "selected_prediction_index": pathsafe(
                run_dir, ArtifactPaths.for_run(run_dir).providers.selected_index,
            ),
            "runtime_policy": pathsafe(
                run_dir, ArtifactPaths.for_run(run_dir).observability.execution_plan,
            ),
        }
        if contract.get("result") != result_paths:
            return False
        if contract.get("execution_evidence") != evidence_paths:
            return False

        execution = contract.get("execution") or {}
        code_identity = provenance.get("code_identity") or {}
        identity_pairs = {
            "pdffast_commit": provenance.get("pdffast_commit"),
            "source_sha256": code_identity.get("source_sha256"),
            "source_dirty": code_identity.get("source_dirty"),
            "algorithm_sha256": code_identity.get("algorithm_sha256"),
            "profile_name": provenance.get("profile_name"),
            "profile_sha256": provenance.get("profile_sha256"),
            "providers_config_sha256": provenance.get("providers_config_sha256"),
            "effective_config_fingerprint": provenance.get("effective_config_fingerprint"),
            "allowed_providers": provenance.get("allowed_providers"),
        }
        if any(execution.get(key) != value for key, value in identity_pairs.items()):
            return False
        if any(
            expected.get(key) is not None and execution.get(key) != expected.get(key)
            for key in (
                "pdffast_commit", "profile_name", "profile_sha256",
                "providers_config_sha256", "effective_config_fingerprint",
                "allowed_providers",
            )
        ):
            return False
        expected_code = expected.get("code_identity")
        if isinstance(expected_code, dict) and any(
            code_identity.get(key) != expected_code.get(key)
            for key in ("source_sha256", "source_dirty", "algorithm_sha256")
        ):
            return False
        expected_runtime = expected.get("provider_runtime")
        if expected_runtime is not None and execution.get("provider_runtime") != expected_runtime:
            return False

        allowed = set(execution.get("allowed_providers") or [])
        runtime = execution.get("provider_runtime")
        if (
            not allowed or not isinstance(runtime, dict) or set(runtime) != allowed
            or any(
                not isinstance(value, dict) or value.get("status") != "READY"
                or value.get("dependency_probe") not in {"PASS", "NOT_RUN"}
                or not isinstance(value.get("identity"), dict)
                for value in runtime.values()
            )
        ):
            return False
        if (
            execution.get("policy_version") != execution_plan.get("version")
            or execution.get("preflight_status") != "PASS"
            or execution.get("audit_passed") is not True
            or execution.get("outputs_written") is not True
            or audit.get("validation", {}).get("pass") is not True
        ):
            return False

        summary = production_manifest.get("summary") or {}
        planned = execution.get("planned_task_count")
        accepted = execution.get("accepted_task_count")
        terminal = execution.get("terminal_preserve_count")
        failures = execution.get("pipeline_failure_count")
        escalated = execution.get("escalated_count")
        attempted = execution.get("attempted_provider_counts")
        selected = execution.get("selected_provider_counts")
        if (
            any(type(value) is not int or value < 0 for value in
                (planned, accepted, terminal, failures, escalated))
            or accepted + terminal + failures != planned
            or not isinstance(attempted, dict) or not isinstance(selected, dict)
            or any(type(value) is not int or value <= 0 for value in attempted.values())
            or any(type(value) is not int or value <= 0 for value in selected.values())
            or set(attempted) - allowed or set(selected) - allowed
            or sum(selected.values()) != accepted
            or (planned == 0 and (attempted or selected or escalated or terminal or failures))
            or (planned > 0 and (not attempted or sum(attempted.values()) < planned))
        ):
            return False
        status = "COMPLETED_WITH_PIPELINE_FAILURES" if failures else "COMPLETED"
        if (
            execution.get("execution_status") != status
            or provenance.get("execution_status") != status
            or production_manifest.get("status") != status
            or provenance.get("planned_task_count") != planned
            or provenance.get("accepted_task_count") != accepted
            or provenance.get("terminal_preserve_count") != terminal
            or provenance.get("pipeline_failure_count") != failures
            or provenance.get("attempted_provider_counts") != attempted
            or provenance.get("selected_provider_counts") != selected
            or summary.get("task_count") != planned
            or summary.get("accepted_task_count") != accepted
            or summary.get("terminal_preserve_count") != terminal
            or summary.get("pipeline_failure_count") != failures
            or summary.get("attempt_provider_counts") != attempted
            or summary.get("selected_provider_counts") != selected
            or summary.get("escalated_count") != escalated
            or execution_plan.get("summary", {}).get("task_count") != planned
        ):
            return False

        artifacts = contract.get("artifacts")
        if not isinstance(artifacts, list):
            return False
        required = {
            "document": result_paths["document"],
            "markdown": result_paths["markdown"],
            "audit": result_paths["audit"],
            "production_execution_manifest": evidence_paths["production_manifest"],
            "selected_prediction_index": evidence_paths["selected_prediction_index"],
            "runtime_escalation_policy": evidence_paths["runtime_policy"],
        }
        if artifact_bytes is None:
            raw_paths = [
                item.get("path") if isinstance(item, dict) else None
                for item in artifacts
            ]
            if any(not isinstance(raw_path, str) for raw_path in raw_paths):
                return False
            artifact_bytes, _ = _read_run_relative_files(run_dir, raw_paths)

        seen_paths = set()
        by_name = {}
        selected_artifacts = {}
        for item in artifacts:
            if not isinstance(item, dict):
                return False
            name = item.get("name")
            raw_path = item.get("path")
            sha = item.get("sha256")
            size = item.get("byte_size")
            media_type = item.get("media_type")
            if (
                not isinstance(name, str) or not isinstance(sha, str)
                or len(sha) != 64 or any(char not in "0123456789abcdef" for char in sha)
                or type(size) is not int or size < 0
                or media_type not in {"application/json", "text/markdown", "text/plain"}
            ):
                return False
            if not isinstance(raw_path, str):
                return False
            if raw_path in seen_paths or raw_path == "result/manifest.json":
                return False
            seen_paths.add(raw_path)
            payload = artifact_bytes.get(raw_path)
            if not isinstance(payload, bytes):
                return False
            byte_count = len(payload)
            digest = hashlib.sha256(payload).hexdigest()
            if (
                byte_count != size or digest != sha
                or (media_type == "application/json" and size < 1)
            ):
                return False
            by_name.setdefault(name, []).append(raw_path)
            if name == "selected_prediction":
                task_id = item.get("task_id")
                if not isinstance(task_id, str) or not task_id or task_id in selected_artifacts:
                    return False
                selected_artifacts[task_id] = raw_path
        if any(by_name.get(name) != [path] for name, path in required.items()):
            return False
        if "result/manifest.json" in seen_paths:
            return False

        selected_items = selected_index.get("items")
        if (
            not isinstance(selected_items, list)
            or selected_index.get("task_count") != planned
            or len(selected_items) != planned
        ):
            return False
        selected_tasks = {}
        selected_dir = pathsafe(run_dir, ArtifactPaths.for_run(run_dir).providers.selected_dir)
        for item in selected_items:
            task_id = item.get("task_id") if isinstance(item, dict) else None
            if not isinstance(task_id, str) or not task_id or task_id in selected_tasks:
                return False
            selected_tasks[task_id] = item
        if (
            set(selected_artifacts) != set(selected_tasks)
            or production_manifest.get("selected_predictions") != selected_items
        ):
            return False

        plan_items = execution_plan.get("tasks")
        if not isinstance(plan_items, list) or len(plan_items) != planned:
            return False
        plan_tasks = {}
        for task in plan_items:
            task_id = task.get("task_id") if isinstance(task, dict) else None
            if not isinstance(task_id, str) or not task_id or task_id in plan_tasks:
                return False
            plan_tasks[task_id] = task
        if set(plan_tasks) != set(selected_tasks):
            return False

        observed_attempts: Counter[str] = Counter()
        observed_selected: Counter[str] = Counter()
        observed_dispatch = Counter()
        observed_accepted = observed_terminal = observed_failures = observed_escalated = 0
        for task_id, raw_path in selected_artifacts.items():
            if raw_path != f"{selected_dir}/{task_id}.json":
                return False
            if selected_tasks[task_id].get("selected_prediction") != str(
                ArtifactPaths.for_run(run_dir).providers.selected_prediction(task_id)
            ):
                return False
            prediction = json.loads(artifact_bytes[raw_path])
            if not isinstance(prediction, dict):
                return False
            task = plan_tasks[task_id]
            if prediction.get("task_id") != task_id:
                return False
            chain = [
                item.get("provider") for item in task.get("provider_chain", [])
                if isinstance(item, dict)
            ]
            attempts = prediction.get("attempts")
            if not chain or not isinstance(attempts, list) or not 0 < len(attempts) <= len(chain):
                return False
            accepted_positions = []
            for position, attempt in enumerate(attempts):
                if not isinstance(attempt, dict):
                    return False
                provider = attempt.get("provider")
                canonical = attempt.get("canonical")
                if (
                    type(attempt.get("chain_index")) is not int
                    or attempt.get("chain_index") != position
                    or provider != chain[position] or provider not in allowed
                    or type(attempt.get("accepted")) is not bool
                    or not isinstance(canonical, dict)
                    or canonical.get("task_id") != task_id
                    or (canonical.get("provider") or {}).get("name") != provider
                ):
                    return False
                observed_attempts[provider] += 1
                observed_dispatch[position, provider, task_id] += 1
                if attempt["accepted"]:
                    accepted_positions.append(position)

            selected_provider = prediction.get("selected_provider")
            is_terminal = prediction.get("terminal_fallback_applied")
            is_failure = prediction.get("pipeline_failure")
            index_item = selected_tasks[task_id]
            if (
                type(is_terminal) is not bool or type(is_failure) is not bool
                or index_item.get("selected_provider") != selected_provider
                or index_item.get("terminal_fallback_applied") is not is_terminal
                or index_item.get("pipeline_failure") is not is_failure
            ):
                return False
            if selected_provider is not None:
                if (
                    accepted_positions != [len(attempts) - 1]
                    or selected_provider != attempts[-1]["provider"]
                    or prediction.get("selected_canonical") != attempts[-1]["canonical"]
                    or is_terminal or is_failure
                ):
                    return False
                observed_accepted += 1
                observed_selected[selected_provider] += 1
            else:
                terminal_action = (task.get("terminal_fallback") or {}).get("action")
                if (
                    accepted_positions or len(attempts) != len(chain)
                    or prediction.get("selected_canonical") is not None
                    or is_terminal is not bool(terminal_action)
                    or is_failure is is_terminal
                    or prediction.get("terminal_fallback_action")
                    != (terminal_action if is_terminal else None)
                ):
                    return False
                observed_terminal += int(is_terminal)
                observed_failures += int(is_failure)
            observed_escalated += int(len(attempts) > 1)

        batch_dispatch = Counter()
        for batch in production_manifest.get("batch_history", []):
            if (
                not isinstance(batch, dict) or type(batch.get("wave")) is not int
                or not isinstance(batch.get("provider"), str)
                or not isinstance(batch.get("task_ids"), list)
            ):
                return False
            batch_dispatch.update(
                (batch["wave"], batch["provider"], task_id)
                for task_id in batch["task_ids"]
            )
        if (
            observed_dispatch != batch_dispatch
            or dict(sorted(observed_attempts.items())) != attempted
            or dict(sorted(observed_selected.items())) != selected
            or observed_accepted != accepted or observed_terminal != terminal
            or observed_failures != failures or observed_escalated != escalated
        ):
            return False

        return True
    except (
        OSError, ValueError, KeyError, TypeError, AttributeError,
        JSONSchemaValidationError, JSONSchemaSchemaError,
    ):
        return False


def pathsafe(run_dir: Path, path: Path) -> str:
    return Path(path).resolve(strict=False).relative_to(Path(run_dir).resolve(strict=True)).as_posix()


def summarize_parse(
    run_dir: Path, returncode: int, expected: dict, *, input_sha256: str | None,
) -> dict:
    try:
        requested_run_dir = Path(run_dir)
        if requested_run_dir.is_symlink():
            raise ValueError("run directory cannot be a symlink")
        resolved_run_dir = requested_run_dir.resolve(strict=True)
        paths = ArtifactPaths.for_run(resolved_run_dir)

        def relative(path: Path) -> str:
            return Path(path).relative_to(resolved_run_dir).as_posix()

        manifest_path = relative(paths.result.manifest_json)
        initial_payloads, root_identity = _read_run_relative_files(
            resolved_run_dir, [manifest_path],
        )
        manifest = json.loads(initial_payloads[manifest_path])
        if not isinstance(manifest, dict):
            raise ValueError("root manifest must be a JSON object")

        contract = manifest.get("execution_contract")
        descriptor_paths = []
        if isinstance(contract, dict) and isinstance(contract.get("artifacts"), list):
            for item in contract["artifacts"]:
                if isinstance(item, dict) and isinstance(item.get("path"), str):
                    descriptor_paths.append(item["path"])

        fixed_paths = {
            "audit": relative(paths.result.audit_json),
            "profile": relative(paths.native.profile),
            "execution_plan": relative(paths.observability.execution_plan),
            "production_manifest": relative(paths.providers.production_manifest),
            "selected_index": relative(paths.providers.selected_index),
            "document": relative(paths.result.document_json),
            "markdown": relative(paths.result.document_md),
        }
        requested_paths = list(dict.fromkeys([
            *fixed_paths.values(),
            *descriptor_paths,
        ]))
        artifact_bytes, _ = _read_run_relative_files(
            resolved_run_dir,
            requested_paths,
            expected_root_identity=root_identity,
        )
        artifact_bytes.update(initial_payloads)

        def read_json(relative_path: str) -> dict:
            value = json.loads(artifact_bytes[relative_path])
            if not isinstance(value, dict):
                raise ValueError(f"expected a JSON object: {relative_path}")
            return value

        provenance = manifest.get("parser_provenance") or {}
        audit = read_json(fixed_paths["audit"])
        profile = read_json(fixed_paths["profile"])
        execution = read_json(fixed_paths["execution_plan"])
        internal = read_json(fixed_paths["production_manifest"])
        selected_index = read_json(fixed_paths["selected_index"])
        document = read_json(fixed_paths["document"])
        markdown_text = artifact_bytes[fixed_paths["markdown"]].decode("utf-8")

        contract_verified = _verify_execution_contract(
            resolved_run_dir,
            manifest=manifest,
            provenance=provenance,
            expected=expected,
            input_sha256=input_sha256,
            audit=audit,
            execution_plan=execution,
            production_manifest=internal,
            selected_index=selected_index,
            artifact_bytes=artifact_bytes,
        )
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
        markdown_written = True
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
            and contract_verified
            and bool(markdown_text.strip())
            and type(page_count) is int and page_count > 0
            and document.get("page_count") == page_count
            and isinstance(document.get("pages"), list) and len(document["pages"]) == page_count
            and manifest.get("run_id") == resolved_run_dir.name and input_matches
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
            "execution_contract_verified": contract_verified,
            "input_sha256_matched": input_matches,
            "profile_sha256": provenance.get("profile_sha256"),
            "effective_config_fingerprint": provenance.get("effective_config_fingerprint"),
            "execution_status": provenance.get("execution_status"),
            "planned_task_count": summary.get("task_count"), "planned_routes": planned_routes,
            "attempted_provider_counts": attempted, "selected_provider_counts": selected,
            "audit_passed": audit_passed, "markdown_written": markdown_written,
            "canonical_written": bool(document), "manifest_written": True,
            "forbidden_attempt_count": unexpected,
        }
    except (
        OSError, ValueError, KeyError, TypeError, AttributeError,
        json.JSONDecodeError, UnicodeDecodeError,
    ) as exc:
        return {
            "acceptance": "FAIL",
            "page_count": None,
            "execution_contract_verified": False,
            "input_sha256_matched": False,
            "profile_sha256": None,
            "effective_config_fingerprint": None,
            "execution_status": None,
            "planned_task_count": None,
            "planned_routes": {},
            "attempted_provider_counts": None,
            "selected_provider_counts": None,
            "audit_passed": False,
            "markdown_written": False,
            "canonical_written": False,
            "manifest_written": False,
            "forbidden_attempt_count": None,
            "verification_error": type(exc).__name__,
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
