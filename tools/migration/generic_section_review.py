"""Run real PDFs and write a readable review of template removal.

Use an existing Provider runtime by running this script with its Python interpreter
and passing its project root as ``--runtime-root``. Production configuration is
read from this checkout and is never changed.
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from pdffast import PDFFastParser, ParserConfig
from pdffast.providers.registry import ProviderRegistry
from pdffast.providers.runtime_normalization import normalize_runtime_result


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _range(section: dict) -> str:
    return f"{section.get('start_page', '?')}–{section.get('end_page', '?')}"


def _cell(value: object) -> str:
    return str(value or "—").replace("|", "\\|").replace("\n", " ")


def write_review(case_dir: Path, historical_run: Path) -> None:
    for name in ("document.md", "document.json", "audit.json"):
        shutil.copyfile(case_dir / "result" / name, case_dir / name)
    current = _json(case_dir / "03_stage3/section_alignment.json")
    evidence = _json(case_dir / "07_stage7/evidence_manifest.json")
    audit = _json(case_dir / "audit.json")
    summary = [
        "# Observed sections", "",
        "| # | observed title | pages | confidence/status | evidence |",
        "|---:|---|---|---|---|",
    ]
    for index, section in enumerate(current["sections"], 1):
        summary.append(
            f"| {index} | {_cell(section['title'])} | {_range(section)} | "
            f"{_cell(section.get('boundary_confidence'))} | {_cell(section.get('structure_evidence'))} |"
        )
    summary.extend(["", "## Unresolved regions", ""])
    for region in current["unresolved_regions"]:
        summary.append(f"- Pages {_range(region)}: {_cell(region.get('reason'))}")
    if not current["unresolved_regions"]:
        summary.append("- None")
    summary.extend([
        "", "## Accounting and audit", "",
        f"- Native words: {evidence['summary'].get('valid_raw_word_count')}",
        f"- Accounted words: {evidence['summary'].get('accounted_word_count')}",
        f"- Unaccounted native words: {evidence['summary'].get('unaccounted_native_word_count')}",
        f"- Audit status: {_cell(audit.get('status'))}", "",
    ])
    (case_dir / "section_summary.md").write_text("\n".join(summary), encoding="utf-8")

    old_path = historical_run / "03_stage3/section_alignment.json"
    if not old_path.exists():
        (case_dir / "section_comparison.md").write_text("Historical section artifact unavailable.\n", encoding="utf-8")
        return
    old = _json(old_path)
    old_by_start = {int(s["start_page"]): s for s in old.get("sections", [])}
    new_by_start = {int(s["start_page"]): s for s in current["sections"]}
    comparison = [
        "# Historical vs observed sections", "",
        f"Historical artifact: `{old_path}`", "",
        "| start page | before title | before pages | after observed title | after pages | change |",
        "|---:|---|---|---|---|---|",
    ]
    for page in sorted(old_by_start.keys() | new_by_start.keys()):
        before = old_by_start.get(page)
        after = new_by_start.get(page)
        if before and after:
            changes = []
            if before.get("title") != after.get("title"):
                changes.append("title")
            if _range(before) != _range(after):
                changes.append("page range")
            change = ", ".join(changes) or "same"
        else:
            change = "removed template section" if before else "new observed section"
        comparison.append(
            f"| {page} | {_cell(before.get('title') if before else None)} | {_range(before) if before else '—'} | "
            f"{_cell(after.get('title') if after else None)} | {_range(after) if after else '—'} | {change} |"
        )
    comparison.extend(["", "## Unresolved after removal", ""])
    for region in current["unresolved_regions"]:
        comparison.append(f"- Pages {_range(region)}: {_cell(region.get('reason'))}")
    if not current["unresolved_regions"]:
        comparison.append("- None")
    comparison.append("")
    comparison_text = "\n".join(comparison)
    (case_dir / "section_comparison.md").write_text(comparison_text, encoding="utf-8")
    comparison_dir = case_dir.parent / "comparison"
    comparison_dir.mkdir(parents=True, exist_ok=True)
    (comparison_dir / f"{case_dir.name}_sections.md").write_text(comparison_text, encoding="utf-8")

    old_flow_path = historical_run / "06_stage6/normalized_text_flow.json"
    old_evidence_path = historical_run / "07_stage7/evidence_manifest.json"
    if old_flow_path.exists() and old_evidence_path.exists():
        current_flow = _json(case_dir / "06_stage6/normalized_text_flow.json")
        old_flow = _json(old_flow_path)
        old_evidence = _json(old_evidence_path)
        current_records = [
            (record.get("text"), record.get("source_pages"), record.get("source_word_indices"))
            for record in current_flow.get("records", [])
        ]
        old_records = [
            (record.get("text"), record.get("source_pages"), record.get("source_word_indices"))
            for record in old_flow.get("records", [])
        ]
        current_words = evidence["summary"]
        old_words = old_evidence["summary"]
        keys = (
            "valid_raw_word_count", "accounted_word_count", "accounted_table_word_count",
            "unaccounted_native_word_count",
        )
        checks = [
            "# Native content comparison", "",
            f"- Ordered Text Flow records including word/page provenance equal historical: **{current_records == old_records}**",
            f"- Text Flow record count: before {len(old_records)}, after {len(current_records)}",
            "", "| metric | before | after |", "|---|---:|---:|",
        ]
        for key in keys:
            checks.append(f"| {key} | {old_words.get(key)} | {current_words.get(key)} |")
        checks.append("")
        (case_dir / "content_check.md").write_text("\n".join(checks), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-root", required=True, type=Path)
    parser.add_argument("--cases", nargs="+", default=[f"case_{i:03d}" for i in range(1, 6)])
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    reference = args.runtime_root.resolve()
    provider_configs = _json(root / "configs/providers.json")["providers"]
    # The reference checkout still has the verified legacy worker environments.
    # Point this one-off review run at them without changing the frozen policy or
    # the project's production providers.json.
    for name, environment in (
        ("docling_local", ".venv-docling"),
        ("mineru_local", ".venv-mineru"),
        ("marker_local", ".venv-marker"),
    ):
        provider = provider_configs[name]
        old_prefix = f"runtimes/{name.removesuffix('_local')}/.venv"
        provider["python_executable"] = str(reference / environment / "bin/python")
        artifacts = provider.get("required_artifacts", [])
        provider["required_artifacts"] = [
            value.replace(old_prefix, environment, 1) if value.startswith(old_prefix) else value
            for value in artifacts
        ]
        checksums = provider.get("required_artifact_sha256", {})
        provider["required_artifact_sha256"] = {
            (key.replace(old_prefix, environment, 1) if key.startswith(old_prefix) else key): value
            for key, value in checksums.items()
        }
    config = ParserConfig(
        project_root=root,
        output_root=root / "outputs/template_removal_review",
        output_mode="full",
        provider_configs=provider_configs,
        registry=ProviderRegistry(base_dir=reference),
        normalizer=normalize_runtime_result,
    )
    pdffast = PDFFastParser(config=config)
    for case in args.cases:
        pdf = reference / "benchmark/samples/real" / f"{case}.pdf"
        print(f"Parsing {case}: {pdf}", flush=True)
        pdffast.parse(pdf, run_id=case, case_id=case)
        case_dir = config.output_root / case
        write_review(case_dir, reference / "outputs/pipeline_runs" / f"{case}_final_bench_v1")
        print(f"Review ready: {case_dir}", flush=True)


if __name__ == "__main__":
    main()
