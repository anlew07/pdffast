# Provider Runtime Environments

日期：2026-09-20  
状态：Phase 3 六个 Production Provider 环境已落地并完成单任务验证。

## 1. 目标与边界

Production Provider Closure 只包含：

```text
rapidocr_ch_light
paddleocr_v5_mobile
paddleocr_vl_16
mineru_local
marker_local
docling_local
```

`pp_structure_v3_light`、`tesseract_chi_sim`、独立 Surya Provider 和 generic CLI
不进入生产环境规划。曾参与 benchmark 不等于 production runtime dependency。

Python package 与模型 cache 分开管理：包安装在 V2 自己的环境；现有用户级 cache 原地共享。
V2 不以旧工程的 `.venv*` 作为解释器或 import 路径，也不把模型复制进 Git repository。

## 2. 环境拓扑

### `/Users/admin/Workspace/pdffast-v2/.venv`

职责：PDFFast Core 与进程内 Provider host。

规划版本（来自旧生产环境审计，不代表本轮已安装）：

```text
PDFFast Core
rapidocr 3.9.2
onnxruntime 1.30.0
paddleocr 3.6.0
paddlepaddle 3.2.1
paddlex 3.6.1
```

承载 Provider：

```text
rapidocr_ch_light
paddleocr_v5_mobile
paddleocr_vl_16
```

RapidOCR 与 Paddle 两条线路当前没有证据表明需要额外隔离环境；两种 Paddle Provider
共享同一 Paddle/PaddleX runtime 和用户级 PaddleX cache。

### `/Users/admin/Workspace/pdffast-v2/.venv-mineru`

职责：`mineru_local` persistent subprocess worker。规划包版本为 `mineru 3.4.5`。
独立环境的依据是生产闭包依赖、已有 subprocess worker 边界，以及 Torch/Transformers
依赖与主环境隔离的实际价值。

### `/Users/admin/Workspace/pdffast-v2/.venv-marker`

职责：`marker_local` persistent subprocess worker。规划包版本为 `marker-pdf 2.0.0`。
Marker 内部使用 Surya 组件不等于启用独立 Surya Provider。

### `/Users/admin/Workspace/pdffast-v2/.venv-docling`

职责：`docling_local` persistent subprocess worker。安装 `docling 2.127.0` 与
`onnxruntime 1.30.0`。ONNX Runtime 是 Docling 自动 OCR 选择的显式保障，使其使用
RapidOCR wheel 自带 ONNX 权重并在 preflight 阶段阻止 Torch 下载型 fallback。

除以上四个环境外，本阶段不新增 Provider 环境。尤其不为 PP-Structure、Tesseract、
独立 Surya 或 generic CLI 创建环境。

## 3. 共享模型与 cache

### PaddleX / PaddleOCR

```text
共享根目录：/Users/admin/.paddlex
当前大小：约 3.0 GB
显式变量：PADDLE_PDX_CACHE_HOME=/Users/admin/.paddlex

PP-OCRv5 mobile detection:
  /Users/admin/.paddlex/official_models/PP-OCRv5_mobile_det
PP-OCRv5 mobile recognition:
  /Users/admin/.paddlex/official_models/PP-OCRv5_mobile_rec
PaddleOCR VL 1.6:
  /Users/admin/.paddlex/official_models/PaddleOCR-VL-1.6
```

这三个目录已经存在。新环境应指向共享 cache，并在离线模式验证；不得触发首次运行下载。

### Hugging Face

```text
共享根目录：/Users/admin/.cache/huggingface
当前大小：约 3.2 GB
显式变量：HF_HOME=/Users/admin/.cache/huggingface
离线验证：HF_HUB_OFFLINE=1
```

生产闭包已发现的仓库 cache：

```text
MinerU:
  /Users/admin/.cache/huggingface/hub/models--opendatalab--PDF-Extract-Kit-1.0

Marker / Surya transitive models:
  /Users/admin/.cache/huggingface/hub/models--datalab-to--surya-ocr-2-gguf
  /Users/admin/.cache/huggingface/hub/models--datalab-to--surya_layout2

Docling:
  /Users/admin/.cache/huggingface/hub/models--docling-project--docling-models
  /Users/admin/.cache/huggingface/hub/models--docling-project--docling-layout-heron
```

MinerU 的已审计 snapshot 与配置：

```text
/Users/admin/.cache/huggingface/hub/models--opendatalab--PDF-Extract-Kit-1.0/
  snapshots/ed6b654c018d742e65a17671e379c5e6ecc87ec9

MINERU_TOOLS_CONFIG_JSON=/Users/admin/mineru.json
MINERU_MODEL_SOURCE=local
```

### RapidOCR

RapidOCR 的约 31 MB ONNX 模型是 wheel package data。安装新的 V2 Python package 时会在
新环境中物化 package data；这不是独立模型下载，也不能通过引用旧工程
`.venv/lib/.../site-packages` 来规避包安装。

## 4. 安装后的验证顺序

生产 Provider 已按以下顺序完成验证；后续环境重建沿用同一顺序：

```text
package import
  -> provider preflight
  -> existing cache discovery（offline/cache-only）
  -> single-task smoke test
```

任一步发现缺失都应停止该 Provider 的验证，并报告：缺失 artifact、预期路径、来源、估算大小
及是否会产生外部成本。只有生产必需 artifact 确认不存在并再次获批后，才加入下载计划。
当前显式模型下载计划仍为 `0`。Docling 首次 smoke 曾因缺少 ONNX Runtime 触发
RapidOCR Torch 权重自动下载；该次运行已中止，原环境整体隔离保留，最终环境重建后
使用 package-provided ONNX 权重完成离线验证。完整记录见
`docs/PROVIDER_RUNTIME_VALIDATION.md`。

## 5. 配置语义

生产 Registry 只读取：

```text
runtime_enabled
```

benchmark 默认选择只读取：

```text
benchmark_enabled
```

`benchmark_enabled=false` 不会阻止生产 runtime resolve；`runtime_enabled=false` 必须阻止
Provider 进入 production executor。Pipeline 启动时会先验证 frozen policy closure 是
runtime-enabled Registry Provider 集合的子集，闭包不完整时在创建 Provider 或输出文件前失败。

## 6. Core 与企业服务边界

当前只迁移解析 Core，不实现 FastAPI。依赖方向固定为：

```text
HTTP / FastAPI Service adapter
  -> PDFFast Core application API
  -> Provider host / worker boundary

PDFFast Core
  - 不依赖 FastAPI、Starlette、UploadFile、HTTP request/response 类型或 Celery
  - 不管理上传、鉴权、HTTP 生命周期或任务队列
  - 接受文件路径与普通 Python 配置
```

未来入口应允许类似：

```python
result = parser.parse(pdf_path)
```

薄 service adapter 只负责把 HTTP 输入转换为本地文件路径和 Core 参数，再把 Core 结果映射为
HTTP response；增加 service adapter 不应修改 parsing Pipeline、route policy 或 Provider chain。
