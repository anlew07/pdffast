# Provider Runtime Validation

验证日期：2026-09-20 至 2026-09-21
平台：macOS arm64  
Python：3.12.13  
安装器：uv 0.11.28

本文记录 Production Provider Closure 的真实环境落地证据。`Download occurred`
专指模型/权重下载；Python package 安装本身不计作模型下载。

## Validation matrix

| Provider | Python environment | Package version | Import | Preflight | Existing cache reused | Download occurred | Single-task execution | Canonical normalization | Worker cleanup |
|---|---|---|---|---|---|---|---|---|---|
| `rapidocr_ch_light` | `/Users/admin/Workspace/pdffast-v2/.venv` | `rapidocr 3.9.2`; `onnxruntime 1.30.0` | PASS | PASS | N/A — weights are wheel package data | NO | PASS | PASS | PASS — in-process `close()` |
| `paddleocr_v5_mobile` | `/Users/admin/Workspace/pdffast-v2/.venv` | `paddleocr 3.6.0`; `paddlepaddle 3.2.1`; `paddlex 3.6.1` | PASS | PASS | YES — PaddleX | NO | PASS | PASS | PASS — in-process `close()` |
| `paddleocr_vl_16` | `/Users/admin/Workspace/pdffast-v2/.venv` | `paddleocr 3.6.0`; `paddlepaddle 3.2.1`; `paddlex[ocr] 3.6.1` | PASS | PASS | YES — PaddleX | NO | PASS | PASS | PASS — in-process `close()` |
| `mineru_local` | `/Users/admin/Workspace/pdffast-v2/.venv-mineru` | `mineru[pipeline] 3.4.5`; `six 1.17.0` | PASS | PASS | YES — Hugging Face snapshot | NO | PASS | PASS | PASS — worker PID exited |
| `marker_local` | `/Users/admin/Workspace/pdffast-v2/.venv-marker` | `marker-pdf 2.0.0`; `surya-ocr 0.22.1` | PASS | PASS | YES — Hugging Face + Datalab caches | NO | PASS — REGION + INLINE | PASS | PASS — worker and spawned servers exited |
| `docling_local` | `/Users/admin/Workspace/pdffast-v2/.venv-docling` | `docling 2.127.0`; `onnxruntime 1.30.0` | PASS | PASS | YES — Hugging Face + wheel weights | YES — aborted first attempt only; final environment/smoke NO | PASS | PASS | PASS — worker PID exited |

## Step 1 — RapidOCR

### Installation

Installed into the V2-owned main environment with exact versions:

```text
uv pip install --python /Users/admin/Workspace/pdffast-v2/.venv/bin/python \
  rapidocr==3.9.2 onnxruntime==1.30.0
```

The environment does not include the old project's virtualenv in `sys.path` and no
old virtualenv executable was used.

### Package-provided weights

RapidOCR 3.9.2 contains three ONNX files under the new environment:

```text
.venv/lib/python3.12/site-packages/rapidocr/models/PP-OCRv6_det_small.onnx
  9,929,594 bytes
.venv/lib/python3.12/site-packages/rapidocr/models/PP-OCRv6_rec_small.onnx
  21,234,383 bytes
.venv/lib/python3.12/site-packages/rapidocr/models/ch_ppocr_mobile_v2.0_cls_mobile.onnx
  585,532 bytes
```

Initialization logged `File exists and is valid` for all three files. No additional
model path was created and no model download occurred.

### Smoke evidence

Read-only input:

```text
/Users/admin/Workspace/pdffast/outputs/8_quality_gate/case_006_v032/
  probe_crops/p0001_p0001_r002.png
```

Observed result:

```text
Registry resolve: PASS
Preflight: PASS (rapidocr import and RapidOCR symbol available)
Raw status: SUCCESS
Raw OCR line count: 2
Raw text length: 12
Canonical status: SUCCESS
Canonical text availability: AVAILABLE
Canonical text length: 12
Provider close: PASS
```

### Step 1 regression gate

```text
Provider + Registry + fake executor focused suite: 20 passed, 5 skipped
Full default suite: 56 passed, 30 skipped
Reference-bound full suite: 81 passed, 5 skipped
```

The five reference-bound skips are only the not-yet-installed Docling, Marker,
MinerU, and two Paddle optional Provider preflight cases.

Frozen route config SHA-256 remains:

```text
0d999777e130de54ff25248c02cf39ae37e9fe7c5ef9231650aa3304008772d3
```

## Step 2 — PaddleOCR mobile and PaddleOCR-VL

### Cache discovery before installation

All production-required directories existed before Provider initialization:

```text
/Users/admin/.paddlex/official_models/PP-OCRv5_mobile_det
  4.8 MB, 21 files, directory mtime 2026-09-11T19:28:06+0800
/Users/admin/.paddlex/official_models/PP-OCRv5_mobile_rec
  16 MB, 21 files, directory mtime 2026-09-11T19:28:11+0800
/Users/admin/.paddlex/official_models/PP-DocLayoutV3
  directory mtime 2026-09-11T18:43:27+0800
/Users/admin/.paddlex/official_models/PaddleOCR-VL-1.6
  1.8 GB, 63 files, directory mtime 2026-09-11T18:45:57+0800
```

The same mtimes were observed after both smokes. PaddleX logged `Model files already
exist. Using cached files` for every selected model.

### Installation

```text
uv pip install --python /Users/admin/Workspace/pdffast-v2/.venv/bin/python \
  paddleocr==3.6.0 paddlepaddle==3.2.1 paddlex==3.6.1
```

The first PaddleOCR-VL initialization reported that the official OCR optional
dependency set was absent and explicitly required `paddlex[ocr]` at the installed
PaddleX version. The exact-version extra was then installed:

```text
uv pip install --python /Users/admin/Workspace/pdffast-v2/.venv/bin/python \
  'paddlex[ocr]==3.6.1'
```

This installed Python runtime dependencies only. It did not download a model or
change the frozen Paddle package versions.

### Offline/cache-only settings

Both smokes used:

```text
PADDLE_PDX_CACHE_HOME=/Users/admin/.paddlex
PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True
HF_HOME=/Users/admin/.cache/huggingface
HF_HUB_OFFLINE=1
```

### `paddleocr_v5_mobile` smoke

Read-only input was the same `p0001_p0001_r002.png` used for Step 1.

```text
Registry resolve: PASS
Preflight: PASS (paddleocr=3.6.0 PaddleOCR=ok)
Cache: PP-OCRv5_mobile_det + PP-OCRv5_mobile_rec reused
Raw status: SUCCESS
Raw OCR line count: 1
Raw text length: 12
Canonical status: SUCCESS
Canonical text availability: AVAILABLE
Canonical text length: 12
Provider close: PASS
```

### `paddleocr_vl_16` smoke

```text
Registry resolve: PASS
Preflight: PASS (paddleocr=3.6.0 PaddleOCRVL=ok)
Cache: PP-DocLayoutV3 + PaddleOCR-VL-1.6 reused
Model backend: native Paddle dynamic graph, CPU
Raw status: SUCCESS
Raw Markdown length: 14
Canonical status: SUCCESS
Canonical text availability: AVAILABLE
Canonical text length: 12
Canonical reading blocks availability: AVAILABLE
Provider close: PASS
```

### Step 2 regression gate

```text
Provider + Registry + fake executor focused suite: 22 passed, 3 skipped
Full default suite: 58 passed, 28 skipped
Reference-bound full suite: 83 passed, 3 skipped
```

The three remaining reference-bound skips are only the not-yet-installed Docling,
Marker, and MinerU optional Provider preflight cases.

## Step 3 — MinerU subprocess worker

### Environment and installation

Created a new V2-owned Python 3.12.13 arm64 environment. The main `.venv` was
verified with `find_spec('mineru') == None`.

```text
uv venv --python 3.12 /Users/admin/Workspace/pdffast-v2/.venv-mineru
uv pip install --python /Users/admin/Workspace/pdffast-v2/.venv-mineru/bin/python \
  mineru==3.4.5
uv pip install --python /Users/admin/Workspace/pdffast-v2/.venv-mineru/bin/python \
  'mineru[pipeline]==3.4.5'
```

The first pipeline smoke exposed an undeclared direct import of `six` in MinerU's
bundled `pytorchocr/data/imaug/operators.py`. The complete worker traceback was
captured before installing the same version present in the reference environment:

```text
uv pip install --python /Users/admin/Workspace/pdffast-v2/.venv-mineru/bin/python \
  six==1.17.0
```

No MinerU version substitution was made.

### Existing model/cache reuse

```text
MINERU_TOOLS_CONFIG_JSON=/Users/admin/mineru.json
MINERU_MODEL_SOURCE=local
HF_HOME=/Users/admin/.cache/huggingface
HF_HUB_OFFLINE=1
TRANSFORMERS_OFFLINE=1

/Users/admin/.cache/huggingface/hub/
  models--opendatalab--PDF-Extract-Kit-1.0/
  snapshots/ed6b654c018d742e65a17671e379c5e6ecc87ec9
```

The snapshot contains 17 symlink-resolved files and approximately 1.2 GB. Its
directory mtime remained `2026-09-15T10:54:04+0800` after the smoke. No model
download occurred and no model was copied into the repository.

### PAGE_DOCUMENT_LAYOUT_PARSE smoke

Read-only input:

```text
/Users/admin/Workspace/pdffast/outputs/9_fallback_units/
  case_001_v010_150dpi/inputs/page/p0001_page.png
```

Observed result:

```text
Registry resolve: PASS
Preflight: PASS (mineru=ok through .venv-mineru subprocess)
Package version: mineru 3.4.5
Capability route: PAGE_DOCUMENT_LAYOUT_PARSE
Raw status: SUCCESS
Raw Markdown length: 389
Raw reference count: 4
Canonical status: SUCCESS
Canonical text availability: AVAILABLE
Canonical text length: 300
Canonical reading blocks availability: AVAILABLE
Worker PID: exited after close; no matching orphan process remained
```

### Step 3 regression gate

The Provider contract was corrected to check isolated environments through their
configured Python executables instead of importing heavy packages in the main
environment.

```text
Provider + Registry + fake executor focused suite: 23 passed, 2 skipped
Full default suite: 59 passed, 27 skipped
Reference-bound full suite: 84 passed, 2 skipped
```

The two remaining reference-bound skips are the not-yet-created Docling and Marker
worker environments.

## Step 4 — Marker subprocess worker

### Environment and installation

Created a V2-owned Python 3.12.13 arm64 environment and installed the frozen
package version:

```text
uv venv --python 3.12 /Users/admin/Workspace/pdffast-v2/.venv-marker
uv pip install --python /Users/admin/Workspace/pdffast-v2/.venv-marker/bin/python \
  marker-pdf==2.0.0
```

The resolved runtime includes `surya-ocr 0.22.1`, `torch 2.14.0`, and
`transformers 5.17.0`. The main environment reports both `marker` and `surya` as
absent, so Marker remains a subprocess-only dependency.

### Existing model/cache reuse

The smoke used offline Hugging Face mode and explicit existing paths:

```text
HF_HOME=/Users/admin/.cache/huggingface
HF_HUB_OFFLINE=1
TRANSFORMERS_OFFLINE=1
MODEL_CACHE_DIR=/Users/admin/Library/Caches/datalab/models
LLAMA_CPP_BINARY=/Users/admin/.local/bin/llama-server

/Users/admin/.cache/huggingface/hub/
  models--datalab-to--surya-ocr-2-gguf/
    snapshots/6a3a4c30e5e74446d4f8b6afd05b2f2da970f470
  models--datalab-to--surya_layout2/
    snapshots/0aee81d5fd9275c0582e545bf3a56944b1e75679
/Users/admin/Library/Caches/datalab/models/
  ocr_error_detection/2025_02_18
```

The GGUF snapshot is approximately 1.4 GB, the layout snapshot approximately
135 MB, and the shared Datalab cache approximately 262 MB. No model was downloaded
or copied into the repository.

### REGION and INLINE smokes

Both tasks used the existing read-only crop:

```text
/Users/admin/Workspace/pdffast/outputs/8_quality_gate/case_006_v032/
  probe_crops/p0001_p0001_r002.png
```

Observed result:

```text
Registry resolve: PASS
Preflight: PASS (marker-pdf=2.0.0 through .venv-marker subprocess)

REGION_MULTIMODAL_PARSE
  Raw status: SUCCESS
  Raw Markdown length: 12
  Canonical status: SUCCESS
  Canonical text: AVAILABLE, 12 characters
  Canonical reading blocks: AVAILABLE

INLINE_CONTEXT_PARSE
  Raw status: SUCCESS
  Raw Markdown length: 12
  Canonical status: SUCCESS
  Canonical text: AVAILABLE, 12 characters
  Canonical reading blocks: AVAILABLE
```

Marker's Surya dependency starts detached FastLayout and OCR Error servers and
configures them to persist after the spawning process exits. `JsonLineWorker`
now captures the worker-owned descendant tree before protocol shutdown and
terminates only surviving descendants after the worker exits. A regression test
uses a deliberately detached child process. The real smoke confirmed the Marker
worker, FastLayout server, OCR Error server/resource tracker, and VLM server all
exited, while the old project's pre-existing shared servers remained untouched.

### Step 4 regression gate

```text
Provider + Registry + fake executor focused suite: 35 passed, 1 skipped
Full default suite: 62 passed, 26 skipped
Reference-bound full suite: 87 passed, 1 skipped
```

The only remaining reference-bound skip is the not-yet-created Docling worker
environment. Frozen route config SHA-256 remains:

```text
0d999777e130de54ff25248c02cf39ae37e9fe7c5ef9231650aa3304008772d3
```

## Step 5 — Docling subprocess worker

### Environment and installation

The final V2-owned Python 3.12.13 arm64 environment contains:

```text
docling 2.127.0
docling-core 2.97.1
docling-ibm-models 4.0.3
onnxruntime 1.30.0
rapidocr 3.9.2 (Docling dependency)
```

`onnxruntime 1.30.0` is an explicit runtime requirement for this environment.
Docling's automatic OCR selection prefers ONNX Runtime when present; without it,
the installed Torch runtime becomes the fallback and RapidOCR attempts to resolve
separate Torch weights. The Docling Provider preflight now imports and reports both
Docling and ONNX Runtime so this condition fails before task execution.

The main environment reports `find_spec('docling') == None`; Docling remains a
subprocess-only dependency.

### Existing model/cache reuse

The successful smoke used:

```text
HF_HOME=/Users/admin/.cache/huggingface
HF_HUB_OFFLINE=1
TRANSFORMERS_OFFLINE=1

/Users/admin/.cache/huggingface/hub/
  models--docling-project--docling-models/
    snapshots/fc0f2d45e2218ea24bce5045f58a389aed16dc23
  models--docling-project--docling-layout-heron/
    snapshots/8f39ad3c0b4c58e9c2d2c84a38465abf757272d8
```

The shared cache directories are approximately 342 MB and 164 MB. Their directory
mtimes remained `2026-09-04T15:34:24+0800` and
`2026-09-04T15:33:57+0800` after the successful smoke.

RapidOCR used the three ONNX weights shipped as package data in the final clean
environment. Its logs reported `File exists and is valid` for detection,
classification, and recognition weights.

### Auto-download incident and clean rebuild

The first offline smoke found that `HF_HUB_OFFLINE` does not govern RapidOCR's
ModelScope downloader. Because ONNX Runtime was absent, Docling selected the Torch
backend, which downloaded three `.pth` files and one dictionary (approximately
31 MB) into the disposable new virtualenv. The smoke was interrupted, and the
entire environment was moved intact to:

```text
/tmp/pdffast-v2-docling-autodownload-quarantine-20260921-1600
```

The final `.venv-docling` was rebuilt from scratch with ONNX Runtime before any
conversion. It contains only RapidOCR's package-provided ONNX weights and the final
successful smoke performed no model download. The quarantined environment is kept
for recoverability and is not referenced by V2.

### PAGE_DOCUMENT_LAYOUT_PARSE smoke

Read-only input:

```text
/Users/admin/Workspace/pdffast/outputs/9_fallback_units/
  case_001_v010_150dpi/inputs/page/p0001_page.png
```

Observed result:

```text
Registry resolve: PASS
Preflight: PASS (docling=2.127.0 onnxruntime=1.30.0)
OCR backend: ONNX Runtime
Raw status: SUCCESS
Raw Markdown length: 331
Raw reference count: 1
Canonical status: SUCCESS
Canonical text availability: AVAILABLE
Canonical text length: 311
Canonical reading blocks availability: AVAILABLE
Worker PID: exited after close; no matching orphan process remained
```

### Step 5 regression gate

```text
Provider + Registry + fake executor focused suite: 36 passed
Full default suite: 63 passed, 25 skipped
Reference-bound full suite: 88 passed
```

All six production Providers now pass their required smoke and canonical
normalization checks. Frozen route config SHA-256 remains:

```text
0d999777e130de54ff25248c02cf39ae37e9fe7c5ef9231650aa3304008772d3
```
