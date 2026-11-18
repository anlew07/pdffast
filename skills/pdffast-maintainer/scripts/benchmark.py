#!/usr/bin/env python3
"""Wrapper around PDFFast's existing Provider Benchmark tools."""
from __future__ import annotations
import argparse, json, subprocess, sys
from pathlib import Path

TOOLS = ("prepare.py", "run.py", "report.py", "evaluate.py")

def make_parser():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="task", required=True)
    for task in ("prepare", "plan", "execute", "compare", "score"):
        s = sub.add_parser(task)
        s.add_argument("--project-root", required=True, type=Path)
        s.add_argument("--out", required=True, type=Path)
        if task == "prepare":
            s.add_argument("--pages", required=True, type=Path)
            s.add_argument("--pdf-dir", required=True, type=Path)
            s.add_argument("--dpi", type=int, default=200)
        if task in ("plan", "execute", "compare"):
            s.add_argument("--manifest", required=True, type=Path)
        if task in ("plan", "execute"):
            s.add_argument("--providers", nargs="+", required=True)
            s.add_argument("--provider-config", type=Path)
            s.add_argument("--allow-unapproved", action="store_true")
        if task == "execute":
            s.add_argument("--confirm-execute", action="store_true")
        if task in ("compare", "score"):
            s.add_argument("--predictions", nargs="+", required=True, type=Path)
            s.add_argument("--truth", type=Path)
    return p

def command(a):
    if a.task == "prepare":
        return "prepare", ["--pages", str(a.pages), "--pdf-dir", str(a.pdf_dir),
                           "--out", str(a.out), "--dpi", str(a.dpi)]
    if a.task in ("plan", "execute"):
        if a.task == "execute" and not a.confirm_execute:
            raise ValueError("real inference requires --confirm-execute")
        opts = ["--manifest", str(a.manifest), "--project-root", str(a.project_root),
                "--providers", *a.providers, "--out", str(a.out)]
        if a.provider_config:
            opts.extend(["--provider-config", str(a.provider_config)])
        if a.allow_unapproved:
            opts.append("--allow-unapproved")
        if a.task == "plan":
            opts.append("--dry-run")
        return "run", opts
    if a.task == "compare":
        opts = ["--manifest", str(a.manifest), "--predictions",
                *(str(x) for x in a.predictions), "--out", str(a.out)]
        if a.truth:
            opts.extend(["--truth", str(a.truth)])
        return "report", opts
    if a.task == "score":
        if not a.truth:
            raise ValueError("score requires manually reviewed --truth")
        return "evaluate", ["--truth", str(a.truth), "--predictions",
                            *(str(x) for x in a.predictions), "--out", str(a.out)]
    raise ValueError(a.task)

def main():
    parser = make_parser()
    a = parser.parse_args()
    root = a.project_root.resolve()
    missing = [f for f in TOOLS if not (root / "tools/provider_benchmark" / f).is_file()]
    if missing:
        parser.error("not a supported PDFFast checkout: " + repr(missing))
    try:
        module, arguments = command(a)
    except ValueError as exc:
        parser.error(str(exc))
    cmd = [sys.executable, "-m", "tools.provider_benchmark." + module, *arguments]
    print(json.dumps({"cwd": str(root), "argv": cmd}, ensure_ascii=False), flush=True)
    try:
        return subprocess.run(cmd, cwd=root, check=False).returncode
    except OSError as exc:
        parser.error(str(exc))

if __name__ == "__main__":
    raise SystemExit(main())
