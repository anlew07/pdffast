#!/usr/bin/env bash
# Install Indra in a dedicated V3 runtime; does not alter other providers.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUNTIME="$ROOT/runtimes/indra"
PYTHON="$RUNTIME/.venv/bin/python"
MODEL_DIR="$RUNTIME/models/indra-ocr"
VERSION="${INDRA_VERSION:-1.1.2}"
REVISION="${INDRA_MODEL_REVISION:-main}"

command -v uv >/dev/null 2>&1 || { echo "ERROR: uv is required" >&2; exit 2; }
test -f "$ROOT/pdffast/providers/indra.py" || { echo "Not a V3 Indra checkout" >&2; exit 2; }
mkdir -p "$RUNTIME/models"
if [[ ! -x "$PYTHON" ]]; then uv venv --python 3.12 "$RUNTIME/.venv"; fi
uv pip install --python "$PYTHON" "indra-ocr==$VERSION"

"$PYTHON" - "$MODEL_DIR" "$REVISION" "$RUNTIME" <<'PY'
import hashlib, json, platform, sys
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path
from huggingface_hub import HfApi, snapshot_download
dest, requested, runtime = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
repo = "datalab-to/indra-ocr"
sha = HfApi().model_info(repo_id=repo, revision=requested).sha
dest.mkdir(parents=True, exist_ok=True)
snapshot_download(repo_id=repo, revision=sha, local_dir=str(dest))
required = ("det.onnx", "rec_cjk.onnx", "order.onnx")
missing = [n for n in required if not (dest / n).is_file()]
if missing:
    raise SystemExit(f"Indra model missing: {missing}")
hashes = {}
for fp in sorted(dest.rglob("*")):
    if fp.is_file() and ".cache" not in fp.relative_to(dest).parts:
        h = hashlib.sha256()
        with fp.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1048576), b""):
                h.update(chunk)
        hashes[str(fp.relative_to(dest))] = h.hexdigest()
record = {
    "component": "indra-ocr", "package_version": version("indra-ocr"),
    "model_repository": repo, "requested_revision": requested,
    "model_revision_sha": sha, "model_dir": str(dest.resolve()),
    "file_sha256": hashes, "python": sys.version.split()[0],
    "platform": platform.platform(),
    "installed_utc": datetime.now(timezone.utc).isoformat(),
    "commercial_model_license_review_required": True,
}
(runtime / "install_manifest.json").write_text(
    json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)
print(f"Model pinned: {sha} ({len(hashes)} files)")
PY
uv pip freeze --python "$PYTHON" > "$RUNTIME/requirements.lock"
echo "Indra installed: $PYTHON"
echo "Next: .venv/bin/python scripts/verify_indra_runtime.py --hashes --preflight"
