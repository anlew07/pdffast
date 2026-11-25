#!/usr/bin/env python3
"""Verify pinned Indra runtime and run optional V3 end-to-end smoke."""
from __future__ import annotations
import argparse, hashlib, json, os, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path

def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1048576), b""):
            h.update(chunk)
    return h.hexdigest()

def verify(root: Path, hashes: bool = False, preflight: bool = False) -> None:
    base = root / "runtimes/indra"
    python = base / ".venv/bin/python"
    manifest = base / "install_manifest.json"
    if not python.is_file() or not manifest.is_file():
        raise RuntimeError("Indra not installed: bash scripts/install_indra_runtime.sh")
    record = json.loads(manifest.read_text(encoding="utf-8"))
    model_dir = base / "models/indra-ocr"
    if Path(record["model_dir"]).resolve() != model_dir.resolve():
        raise RuntimeError("Indra model path mismatch")
    expected = record.get("file_sha256") or {}
    for name in ("det.onnx", "rec_cjk.onnx", "order.onnx"):
        if name not in expected or not (model_dir / name).is_file():
            raise RuntimeError(f"Missing model: {name}")
    if not record.get("model_revision_sha"):
        raise RuntimeError("Missing immutable model revision")
    if hashes:
        for name, digest in expected.items():
            file = model_dir / name
            if not file.is_file() or sha256(file) != digest:
                raise RuntimeError(f"Bad model hash: {name}")
    package = subprocess.run(
        [str(python), "-c", "import importlib.metadata as m; print(m.version('indra-ocr'))"],
        capture_output=True, text=True, check=True
    ).stdout.strip()
    if package != record["package_version"]:
        raise RuntimeError(f"Package mismatch: {package} != {record['package_version']}")
    sys.path.insert(0, str(root))
    from pdffast.providers.profiles import apply_production_profile
    from pdffast.providers.registry import ProviderRegistry, validate_runtime_provider_closure
    config = json.loads((root / "configs/providers.json").read_text(encoding="utf-8"))
    profile = json.loads((root / "configs/profiles/production.indra-triple.json").read_text(encoding="utf-8"))
    providers, routes = apply_production_profile(config["providers"], profile)
    registry = ProviderRegistry(base_dir=root, plugins=config.get("plugins"))
    policy = {"tasks": [{"task_id": route,
              "provider_chain": [{"provider": name} for name in chain]}
              for route, chain in routes.items()]}
    validate_runtime_provider_closure(policy, providers, registry=registry)
    if preflight:
        indra = registry.create("indra_local", providers["indra_local"])
        try:
            probe = indra.preflight()
            if not probe.available:
                raise RuntimeError(probe.detail)
        finally:
            indra.close()
    print(f"PASS: Indra {package}, model revision {record['model_revision_sha']}")

def smoke_pdf(root: Path, pdf: Path) -> Path:
    """Run a real PDF once, keeping full console diagnostics beside its outputs."""
    pdf = pdf.expanduser().resolve()
    if not pdf.is_file():
        raise FileNotFoundError(pdf)
    output_root = root / "outputs/indra_triple_smoke"
    run_id = "smoke_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + f"_{os.getpid()}"
    run_dir = output_root / run_id
    output_root.mkdir(parents=True, exist_ok=True)
    pending_log = output_root / f".{run_id}.console.log"
    log_path = run_dir / "smoke_console.log"
    command = [
        str(root / ".venv/bin/python"), str(root / "scripts/run_pipeline.py"), str(pdf),
        "--project-root", str(root), "--output-root", str(output_root),
        "--run-id", run_id,
        "--provider-profile", str(root / "configs/profiles/production.indra-triple.json"),
    ]
    print(f"PDF: {pdf}", flush=True)
    print(f"Run ID: {run_id}", flush=True)
    print(f"Full console log: {log_path}", flush=True)
    try:
        with pending_log.open("x", encoding="utf-8") as log:
            completed = subprocess.run(
                command, cwd=root, stdout=log, stderr=subprocess.STDOUT, check=False,
            )
    finally:
        if pending_log.is_file():
            run_dir.mkdir(exist_ok=True)
            pending_log.rename(log_path)
    if completed.returncode:
        print(f"FAIL: PDF smoke exited with code {completed.returncode}", file=sys.stderr)
        # Only the last few diagnostic lines belong on screen; never print huge logs.
        with log_path.open("r", encoding="utf-8", errors="replace") as log:
            from collections import deque
            for line in deque(log, maxlen=25):
                print(line.rstrip("\n"), file=sys.stderr)
        raise SystemExit(completed.returncode)
    print("PASS: PDF smoke completed and audit passed.")
    print(f"Markdown: {run_dir / 'result/document.md'}")
    print(f"Canonical JSON: {run_dir / 'result/document.json'}")
    print(f"Audit JSON: {run_dir / 'result/audit.json'}")
    print("Note: verify OCR fidelity manually; audit success is not proof of exact transcription.")
    return run_dir


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    ap.add_argument("--hashes", action="store_true")
    ap.add_argument("--preflight", action="store_true")
    ap.add_argument("--smoke-pdf", type=Path)
    args = ap.parse_args()
    root = args.root.resolve()
    verify(root, args.hashes, args.preflight)
    if args.smoke_pdf:
        smoke_pdf(root, args.smoke_pdf)

if __name__ == "__main__":
    main()
