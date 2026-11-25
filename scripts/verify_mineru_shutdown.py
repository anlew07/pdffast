"""Run fresh, real MinerU inference and natural shutdown in each trial."""

from __future__ import annotations

import argparse
import json
import resource
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from time import monotonic

from PIL import Image, ImageDraw, ImageFont

from pdffast import ParserConfig
from pdffast.application.production_preflight import preflight_snapshot
from pdffast.application.production_profile import load_production_profile
from pdffast.providers.base import ProviderTask
from pdffast.providers.workers import WorkerShutdownError

PROVIDER = "mineru_local"
PROFILE = Path("configs/profiles/production.indra-triple.json")
MODES = ("candidate", "baseline", "env", "api")
CONTROL_VARIABLES = {"ORT_DISABLE_TELEMETRY", "CI", "GITHUB_ACTIONS", "TF_BUILD"}


def _sample(path: Path) -> None:
    image = Image.new("RGB", (740, 220), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=42)
    draw.text((30, 24), "Experiment report", fill="black", font=font)
    draw.text((30, 93), "Sample 2026 - sensor test", fill="black", font=font)
    image.save(path)


def _trial(snapshot, root: Path, source: Path, mode: str, number: int) -> dict:
    started = monotonic()
    folder = root / f"{mode}-{number:02d}"
    folder.mkdir()
    provider = snapshot.registry.create(PROVIDER, snapshot.configs[PROVIDER])
    worker = provider._get_worker()
    if mode != "candidate":
        worker.environment = {
            key: value for key, value in worker.environment.items()
            if key not in CONTROL_VARIABLES
        }
        worker.extra_env.pop("ORT_DISABLE_TELEMETRY", None)
    if mode == "env":
        worker.extra_env["ORT_DISABLE_TELEMETRY"] = "1"
    elif mode == "api":
        worker.worker_code = (
            "import onnxruntime as ort\nort.disable_telemetry_events()\n" + worker.worker_code
        )

    process = None
    inference_ok = False
    acknowledged = False
    error = None
    try:
        try:
            provider.initialize()
            process = worker._process
            prediction = provider.execute(ProviderTask(
                f"{mode}-{number}", "PAGE_DOCUMENT_OCR", source,
                {"raw_output_dir": str(folder)},
            ))
            inference_ok = prediction.status == "SUCCESS" and bool((prediction.markdown or "").strip())
        finally:
            provider.close()
            acknowledged = True
    except WorkerShutdownError as exc:
        acknowledged = exc.acknowledged
        error = str(exc)
    except (OSError, RuntimeError, ValueError) as exc:
        error = str(exc)
    return {
        "mode": mode, "trial": number, "pid": process.pid if process else None,
        "inference_ok": inference_ok, "bye": acknowledged, "error": error,
        "returncode": process.returncode if process else None,
        "elapsed_seconds": round(monotonic() - started, 3),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--count", type=int, default=30)
    parser.add_argument("--jobs", type=int, default=1)
    parser.add_argument("--modes", choices=MODES, nargs="+", default=["candidate"])
    args = parser.parse_args()
    if args.count < 1 or args.jobs < 1 or len(set(args.modes)) != len(args.modes):
        parser.error("count and jobs must be positive, and modes must be unique")
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    config = ParserConfig(project_root=args.project_root, provider_profile=PROFILE)
    snapshot = load_production_profile(config)
    if preflight_snapshot(snapshot, config)["status"] != "PASS":
        parser.exit(2, "production Profile preflight failed\n")

    root = args.output_root.resolve()
    root.mkdir(mode=0o700)
    source = root / "sample.png"
    _sample(source)
    with ThreadPoolExecutor(args.jobs) as pool, (root / "trials.jsonl").open("x") as report:
        pending = [
            pool.submit(_trial, snapshot, root, source, mode, number)
            for number in range(1, args.count + 1) for mode in args.modes
        ]
        passed = True
        for trial in pending:
            entry = trial.result()
            line = json.dumps(entry, allow_nan=False)
            report.write(line + "\n")
            report.flush()
            print(line, flush=True)
            passed &= entry["inference_ok"] and entry["bye"] and entry["returncode"] == 0
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
