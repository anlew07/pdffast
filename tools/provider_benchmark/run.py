"""Run selected PDFFast Providers independently on fixed benchmark page assets.

A benchmark task is *not* a PDFFast Quality Gate decision. For a fair
visual-only comparison, pair each PNG with a raster-only single-page PDF.
This runner never modifies the production Provider configuration on disk.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from collections import Counter
from datetime import datetime, timezone
from functools import partial
from pathlib import Path
from typing import Any, Callable

from pdffast.providers.base import ProviderTask
from pdffast.providers.registry import ProviderRegistry
from pdffast.providers.runtime_normalization import normalize_runtime_result


PDF_WORKER_KINDS = frozenset({"mineru_worker", "marker_worker", "docling_worker"})
VALID_ROUTES = frozenset({
    "PAGE_DOCUMENT_OCR", "PAGE_DOCUMENT_LAYOUT_PARSE",
    "REGION_MULTIMODAL_PARSE", "INLINE_CONTEXT_PARSE",
})
OK_STATUSES = frozenset({"SUCCESS", "SUCCESS_WITH_WARNINGS"})


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for no, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        item = json.loads(line)
        if not isinstance(item, dict):
            raise ValueError(f"{path}:{no}: JSONL row must be an object")
        rows.append(item)
    if not rows:
        raise ValueError(f"{path}: no benchmark rows")
    ids = [row.get("page_id") for row in rows]
    if any(not isinstance(i, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]+", i) for i in ids):
        raise ValueError("page_id must use only ASCII letters, numbers, _, ., : or -")
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate page_id in benchmark manifest")
    return rows


def choose_input(row: dict[str, Any], config: dict[str, Any], base_dir: Path) -> Path | None:
    kind = str(config.get("kind") or "")
    input_type = config.get("benchmark_input") or ("pdf" if kind in PDF_WORKER_KINDS else "image")
    if input_type not in {"pdf", "image"}:
        raise ValueError(f"invalid benchmark_input={input_type!r}")
    value = row.get(input_type)
    if not isinstance(value, str) or not value:
        return None
    path = Path(value).expanduser()
    return (base_dir / path).resolve() if not path.is_absolute() else path


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _safe_id(page_id: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9_.-]", "_", page_id)[:64]
    return clean + "_" + hashlib.sha256(page_id.encode()).hexdigest()[:10]


def run_benchmark(
    *,
    rows: list[dict[str, Any]],
    names: list[str],
    provider_configs: dict[str, dict[str, Any]],
    registry: Any,
    output_dir: Path,
    input_base: Path,
    allow_unapproved: bool = False,
    normalizer: Callable[..., dict[str, Any]] = normalize_runtime_result,
    dry_run: bool = False,
) -> list[dict[str, Any]]:
    """Run sequentially, keeping failures and skipped inputs in the result set."""
    if not names or len(names) != len(set(names)):
        raise ValueError("select at least one unique Provider")
    if not rows:
        raise ValueError("benchmark rows must not be empty")
    for name in names:
        if name not in provider_configs:
            raise ValueError(f"unknown Provider {name}")
        if provider_configs[name].get("benchmark_enabled") is not True and not allow_unapproved:
            raise ValueError(
                f"{name} benchmark_enabled=false; use a reviewed benchmark config "
                "or explicitly pass --allow-unapproved"
            )
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    plan: list[dict[str, Any]] = []
    for name in names:
        cfg = dict(provider_configs[name])
        # Isolation: Registry.create checks runtime_enabled, but benchmark must
        # not change the production setting or its config file.
        cfg["runtime_enabled"] = True
        eligible: list[tuple[dict[str, Any], Path]] = []
        for row in rows:
            route = row.get("capability_route", "PAGE_DOCUMENT_OCR")
            if route not in VALID_ROUTES:
                raise ValueError(f"{row.get('page_id')}: invalid capability_route={route!r}")
            selected = choose_input(row, cfg, Path(input_base))
            plan.append({
                "page_id": row["page_id"], "provider": name, "route": route,
                "input": str(selected) if selected is not None else None,
                "input_exists": bool(selected and selected.is_file()),
            })
            if selected is not None and selected.is_file():
                eligible.append((row, selected))
            elif not dry_run:
                results.append({
                    "page_id": row["page_id"], "provider": name, "status": "SKIPPED_INPUT",
                    "text": None, "elapsed_seconds": None,
                    "reason": f"missing benchmark asset for {name}: {selected}",
                })
        if dry_run or not eligible:
            continue
        instance = None
        error: str | None = None
        preflight_seconds: float | None = None
        init_seconds: float | None = None
        try:
            began = time.perf_counter()
            instance = registry.create(name, cfg)
            preflight = instance.preflight()
            preflight_seconds = time.perf_counter() - began
            if not preflight.available:
                error = f"preflight: {preflight.detail}"
            else:
                began = time.perf_counter()
                instance.initialize()
                init_seconds = time.perf_counter() - began
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
        try:
            if error is not None:
                for row, _ in eligible:
                    results.append({
                        "page_id": row["page_id"], "provider": name, "status": "INIT_FAILED",
                        "text": None, "elapsed_seconds": None, "reason": error,
                        "preflight_seconds": preflight_seconds,
                        "init_seconds": init_seconds,
                    })
                continue
            assert instance is not None
            for row, path in eligible:
                page_id = str(row["page_id"])
                slot = output_dir / "raw" / name / _safe_id(page_id)
                slot.mkdir(parents=True, exist_ok=True)
                task_id = "benchmark_" + _safe_id(page_id)
                route = str(row.get("capability_route", "PAGE_DOCUMENT_OCR"))
                task_type = (
                    "PAGE_FALLBACK" if route.startswith("PAGE_")
                    else "INLINE_CONTEXT_FALLBACK" if route == "INLINE_CONTEXT_PARSE"
                    else "REGION_FALLBACK"
                )
                extra_metadata = row.get("metadata") or {}
                if not isinstance(extra_metadata, dict):
                    raise ValueError(f"{page_id}: metadata must be an object")
                metadata = {
                    **extra_metadata,
                    # Harness-owned fields cannot be overridden by dataset rows.
                    "task_id": task_id, "task_type": task_type,
                    "page_number": row.get("page_number", 1),
                    "source_id": page_id, "capability_route": route,
                    "input_image": str(path), "route_hints": {},
                    # Always isolate temporary Worker files for this attempt.
                    "raw_output_dir": str(slot),
                }
                task = ProviderTask(
                    task_id=task_id, capability_route=route, input_image=path,
                    metadata=metadata,
                )
                started = time.perf_counter()
                record = {
                    "page_id": page_id, "provider": name, "status": "FAILED",
                    "text": None, "input_sha256": _sha256(path),
                    "input_path": str(path), "input_type": path.suffix.lower(),
                    "preflight_seconds": preflight_seconds,
                    "init_seconds": init_seconds,
                }
                try:
                    raw = instance.execute(task)
                    record["elapsed_seconds"] = round(time.perf_counter() - started, 6)
                    record["provider_elapsed_seconds"] = raw.elapsed_seconds
                    record["raw_status"] = raw.status
                    canonical = normalizer(
                        raw, metadata,
                        result_path=slot / "raw.json",
                        manifest_path=slot / "manifest.json",
                    )
                    (slot / "canonical.json").write_text(
                        json.dumps(canonical, ensure_ascii=False, indent=2, default=str) + "\n",
                        encoding="utf-8",
                    )
                    txt = canonical.get("text")
                    record["text"] = txt.get("content") if isinstance(txt, dict) else None
                    canonical_status = str(canonical.get("status") or "")
                    record["canonical_status"] = canonical_status
                    record["status"] = (
                        canonical_status if raw.status in OK_STATUSES
                        and canonical_status in OK_STATUSES else "FAILED"
                    )
                    if record["status"] == "FAILED":
                        record["reason"] = (
                            f"raw_status={raw.status!r} canonical_status={canonical_status!r}"
                        )
                    record["canonical_path"] = str(slot / "canonical.json")
                except Exception as exc:
                    record["elapsed_seconds"] = round(time.perf_counter() - started, 6)
                    record["status"] = "FAILED"
                    record["reason"] = f"{type(exc).__name__}: {exc}"
                results.append(record)
        finally:
            if instance is not None:
                try:
                    instance.close()
                except Exception as exc:
                    # Include teardown failure in a separate manifest, do not
                    # silently turn a real prediction into an incorrect success.
                    results.append({
                        "page_id": "__teardown__", "provider": name,
                        "status": "CLOSE_FAILED", "text": None,
                        "reason": f"{type(exc).__name__}: {exc}",
                    })
    (output_dir / "plan.json").write_text(
        json.dumps({"rows": plan, "dry_run": dry_run}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if not dry_run:
        (output_dir / "predictions.jsonl").write_text(
            "".join(json.dumps(x, ensure_ascii=False, default=str) + "\n" for x in results),
            encoding="utf-8",
        )
        (output_dir / "run_manifest.json").write_text(
            json.dumps({
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                "providers": names,
                "task_count": len(rows),
                "status_counts": dict(Counter(x["status"] for x in results)),
                "allow_unapproved": allow_unapproved,
                "quality_metrics": "NOT_SCORED_NEEDS_GROUND_TRUTH",
                "latency_scope": "execute wall-time excluding preflight/initialization",
            }, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Run independent PDFFast Provider benchmarks")
    parser.add_argument("--manifest", required=True, type=Path, help="JSONL with page_id/image/pdf")
    parser.add_argument("--providers", required=True, nargs="+")
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--provider-config", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--allow-unapproved", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    project_root = args.project_root.resolve()
    config_path = args.provider_config or project_root / "configs/providers.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    registry = ProviderRegistry(base_dir=project_root, plugins=config.get("plugins"))
    normalizer = partial(
        normalize_runtime_result, plugin_normalizer_paths=registry.plugin_normalizers
    )
    results = run_benchmark(
        rows=read_jsonl(args.manifest),
        names=args.providers,
        provider_configs=config["providers"],
        registry=registry, output_dir=args.out, input_base=args.manifest.parent,
        normalizer=normalizer,
        allow_unapproved=args.allow_unapproved,
        dry_run=args.dry_run,
    )
    print(json.dumps({
        "dry_run": args.dry_run, "output_dir": str(args.out),
        "record_count": len(results),
        "status_counts": dict(Counter(x["status"] for x in results)),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
