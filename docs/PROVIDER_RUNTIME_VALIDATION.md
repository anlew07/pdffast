# Provider Runtime Validation

验证日期：2026-09-20  
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
| `mineru_local` | `/Users/admin/Workspace/pdffast-v2/.venv-mineru` | Pending Step 3 | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING |
| `marker_local` | `/Users/admin/Workspace/pdffast-v2/.venv-marker` | Pending Step 4 | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING |
| `docling_local` | `/Users/admin/Workspace/pdffast-v2/.venv-docling` | Pending Step 5 | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING |

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
