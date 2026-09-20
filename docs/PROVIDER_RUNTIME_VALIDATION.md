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
| `paddleocr_v5_mobile` | `/Users/admin/Workspace/pdffast-v2/.venv` | Pending Step 2 | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING | N/A |
| `paddleocr_vl_16` | `/Users/admin/Workspace/pdffast-v2/.venv` | Pending Step 2 | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING | N/A |
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
