# Production Provider Closure Audit

审计日期：2026-09-20  
审计范围：PDFFast v2 Phase 3（仅解析 Core；不包含 HTTP / FastAPI Service）

## 1. 结论

当前冻结生产 runtime 的 Provider Closure 是以下 **6 个 Provider 实例**：

```text
rapidocr_ch_light
paddleocr_v5_mobile
paddleocr_vl_16
mineru_local
marker_local
docling_local
```

`pp_structure_v3_light`、`tesseract_chi_sim`、`surya_local` 和
`generic_cli_example` 不属于 Production Provider Closure。它们即使曾经参与 benchmark，
也不能因此成为 V2 的默认生产依赖。

本次审计没有安装 Python 包、没有创建虚拟环境、没有初始化 Provider、没有执行推理，
也没有下载或改动任何模型/cache。

## 2. 判定口径

两个集合必须严格分开：

- **benchmark candidate**：曾进入 benchmark、frontier、dominated-by 或 capability-emitter
  统计的 Provider；这只能证明它被评测过。
- **production runtime dependency**：能够由当前 router 产生的 route，经当前
  `runtime policy builder` 写入 `provider_chain`，并能被 fallback executor 在某一波次实际调用的
  Provider；这才进入生产闭包。

审计使用以下事实源：

1. `configs/frozen/stage9_route_candidates_prod_v001.json`；
2. `pdffast/fallback/router.py`；
3. `pdffast/fallback/policy.py`；
4. `pdffast/fallback/executor.py`；
5. V2 `configs/providers.json`；
6. 旧工程 `configs/stage9_providers_v011.json`、Stage 9.8 executor 与现有最终生产运行产物。

生产依赖判定不使用 GT、质量评分或“曾经 benchmark”作为替代条件。

## 3. Runtime route 静态展开

### 3.1 PAGE_DOCUMENT_OCR

```text
policy class: PAGE_FAST_OCR_ESCALATION

rapidocr_ch_light          PRIMARY_FAST_PATH
  -> mineru_local          SECONDARY_FALLBACK
  -> paddleocr_vl_16       HEAVY_FALLBACK
  -> pipeline failure      无 terminal fallback
```

三个 Provider 均为生产依赖。后两个即使在当前样本中很少被执行，也会在前序输出状态失败、
text channel 不可用或必需文本为空时变为可达。

### 3.2 PAGE_DOCUMENT_LAYOUT_PARSE

```text
policy class: PAGE_LAYOUT_PARSE_ESCALATION

mineru_local               PRIMARY_LAYOUT_PARSE
  -> marker_local          SECONDARY_LAYOUT_PARSE
  -> docling_local         TERTIARY_LAYOUT_PARSE
  -> pipeline failure      无 terminal fallback
```

接受条件要求非空文本，并且 `reading_blocks` / `tables` 等至少一个必需结构 channel
包含显式 items；平面 OCR 不能代替 layout parse。

这个 route 不在冻结 Stage 9.6.2 benchmark route 文件中，但它存在于当前生产 policy builder，
并且旧工程最终生产运行已经真实产生过：

- `case_001_final_bench_v1`：1 个 layout task，MinerU 被选中；
- `case_003_final_bench_v1`：7 个 layout task，MinerU 被选中。

因此该 route 及其完整 escalation chain 必须纳入生产闭包。其顺序是显式能力契约，
不是由该冻结 benchmark route 排名得出。

### 3.3 REGION_MULTIMODAL_PARSE

```text
REGION_TEXT_FIRST
  rapidocr_ch_light
    -> paddleocr_v5_mobile
    -> marker_local
    -> PRESERVE_SOURCE_REGION_UNRESOLVED

REGION_COMPLEX_GAP_AWARE
  rapidocr_ch_light
    -> marker_local
    -> PRESERVE_SOURCE_REGION_UNRESOLVED

REGION_GENERIC_GAP_AWARE
  rapidocr_ch_light
    -> marker_local
    -> PRESERVE_SOURCE_REGION_UNRESOLVED
```

Region OCR 只是对保留原始视觉区域的 text enrichment；Provider 全部耗尽后保留源区域，
不得把空 OCR 当成内容丢失，也不得从平面文本虚构 relation。

### 3.4 INLINE_CONTEXT_PARSE

```text
policy class: INLINE_MATH_CONTEXT

marker_local               PRIMARY_CONTEXT_PARSE
  -> rapidocr_ch_light     FAST_TEXT_RESCUE
  -> paddleocr_v5_mobile   SECONDARY_TEXT_RESCUE
  -> pipeline failure      无 terminal fallback
```

Marker 是该 route 的 first provider；RapidOCR 和 PaddleOCR mobile 只作 operational rescue。

## 4. Provider Closure 明细

| Provider | 是否曾 benchmark | 是否被 production runtime 引用 | 在哪一种 route 中使用 | 是否 first provider | 是否只作为 escalation | 是否需要独立 Python 环境 | 当前旧环境位置 | 当前模型/cache 位置 | 新项目是否需要安装 | 理由 |
|---|---:|---:|---|---:|---:|---:|---|---|---:|---|
| `rapidocr_ch_light` | 是 | **是** | PAGE OCR、REGION、INLINE | 是：PAGE/REGION | 否 | 否 | `/Users/admin/Workspace/pdffast/.venv` | 模型随包位于 `.venv/lib/python3.12/site-packages/rapidocr/models/`，约 31 MB | **是，生产可选依赖** | PAGE/REGION 主路径；INLINE rescue。新项目不能引用旧 `.venv`，安装同版本包会获得随 wheel 分发的 ONNX 文件，不需要单独下载模型。 |
| `paddleocr_v5_mobile` | 是 | **是** | REGION text-first、INLINE | 否 | **是** | 否；与 Paddle VL 共用同一 Paddle runtime | `/Users/admin/Workspace/pdffast/.venv` | `/Users/admin/.paddlex/official_models/PP-OCRv5_mobile_det`（约 4.8 MB）、`PP-OCRv5_mobile_rec`（约 16 MB） | **是，生产可选依赖** | 两条生产链的末级 OCR rescue。模型已在用户级 PaddleX cache，无需重复下载。 |
| `paddleocr_vl_16` | 是 | **是** | PAGE OCR | 否 | **是** | 否；与 Paddle mobile 共用同一 Paddle runtime | `/Users/admin/Workspace/pdffast/.venv` | `/Users/admin/.paddlex/official_models/PaddleOCR-VL-1.6`（约 1.8 GB）；用户 HF cache 中还有对应 repo 元数据 | **是，生产可选依赖** | PAGE OCR heavy fallback。当前配置为本地 backend，不需要 API key；模型已存在。 |
| `mineru_local` | 是 | **是** | PAGE OCR、PAGE LAYOUT | 是：PAGE LAYOUT | 否 | **是** | `/Users/admin/Workspace/pdffast/.venv-mineru` | `/Users/admin/.cache/huggingface/hub/models--opendatalab--PDF-Extract-Kit-1.0/snapshots/ed6b654c018d742e65a17671e379c5e6ecc87ec9`（约 1.2 GB）；`/Users/admin/mineru.json` 已指向该 snapshot | **是，独立环境** | 是真实 layout 主 Provider，也是 PAGE OCR escalation；已有 persistent subprocess worker，且 Torch/Transformers 栈与主环境隔离有明确价值。 |
| `marker_local` | 是 | **是** | INLINE、REGION、PAGE LAYOUT | 是：INLINE | 否 | **是** | `/Users/admin/Workspace/pdffast/.venv-marker` | HF cache：`models--datalab-to--surya-ocr-2-gguf`（约 1.4 GB）与 `models--datalab-to--surya_layout2`（约 135 MB） | **是，独立环境** | INLINE 主 Provider，也是 REGION/PAGE LAYOUT escalation；已有 persistent subprocess worker。Marker 对 Surya 库/模型的传递依赖不等于把独立 `surya_local` Provider 纳入生产。 |
| `docling_local` | 是 | **是** | PAGE LAYOUT | 否 | **是** | **是** | `/Users/admin/Workspace/pdffast/.venv-docling` | HF cache：`models--docling-project--docling-models`（约 342 MB）、`models--docling-project--docling-layout-heron`（约 164 MB） | **是，独立环境** | PAGE LAYOUT tertiary fallback；已有 subprocess worker，依赖栈独立。虽然旧最终运行尚未升级到它，失败链上仍然可达。 |
| `pp_structure_v3_light` | 是 | **否** | 无 | 否 | 否 | 否 | `/Users/admin/Workspace/pdffast/.venv` | 多个 PP-Structure 模型位于 `/Users/admin/.paddlex/official_models/` | **否** | 只出现在 benchmark/capability 统计和 V2 过宽配置中，当前任何 production `provider_chain` 都未引用。 |
| `tesseract_chi_sim` | 是 | **否** | 无 | 否 | 否 | 否 | 系统 binary：`/opt/homebrew/bin/tesseract` 5.5.3 | Homebrew/Tesseract 系统数据 | **否** | 冻结 benchmark 中出现，但 runtime policy 明确未引用。 |
| `surya_local` | 是，旧 outputs 中有结果；未进入冻结 prod candidate 文件 | **否** | 无 | 否 | 否 | 否 | `/Users/admin/Workspace/pdffast/.venv-surya` | 与 Marker 的传递依赖部分共享 HF cache | **否** | 独立 Surya Provider 被生产 executor 明确禁止；不能因 Marker 内部使用 Surya 组件而恢复该 adapter。 |
| `generic_cli_example` | 否，未发现运行结果 | **否** | 无 | 否 | 否 | 否 | 无 | 无 | **否** | 仅示例配置，不属于生产能力。 |

## 5. 旧生产运行的佐证

旧工程现有 8 个 `case_*_final_bench_v1` Stage 9.8 manifest 合计显示：

```text
selected providers
  rapidocr_ch_light  309
  mineru_local         8
  marker_local         7

attempted providers
  rapidocr_ch_light  317
  mineru_local         8
  marker_local        16
```

这只能证明历史样本实际走到过哪些波次，不能把尚未触发的
`paddleocr_v5_mobile`、`paddleocr_vl_16`、`docling_local` 从闭包中删除：它们在当前失败链上仍可达。

反过来，`pp_structure_v3_light` 即使有大量 benchmark 产物，也因为没有生产链引用而被排除。

## 6. Python 环境与模型缓存必须分开

### 6.1 旧环境现状

```text
.venv          Python 3.12.13  约 1.2 GB
  rapidocr 3.9.2 / onnxruntime 1.30.0
  paddleocr 3.6.0 / paddlepaddle 3.2.1 / paddlex 3.6.1

.venv-docling  Python 3.12.13  约 1.2 GB
  docling 2.127.0 / torch 2.14.0 / transformers 5.17.0

.venv-mineru   Python 3.12.13  约 1.5 GB
  mineru 3.4.5 / torch 2.14.0 / transformers 4.57.6

.venv-marker   Python 3.12.13  约 1.1 GB
  marker-pdf 2.0.0 / torch 2.14.0 / transformers 5.17.0
```

V2 不得把这些旧 virtualenv 设为 runtime interpreter。它们只用于版本与行为审计。

### 6.2 可共享缓存

| Cache | 当前大小 | 复用方式 | 是否需要复制/下载 |
|---|---:|---|---|
| `/Users/admin/.paddlex` | 约 3.0 GB | PaddleX 默认读取；也可显式设置 `PADDLE_PDX_CACHE_HOME=/Users/admin/.paddlex` | 不需要 |
| `/Users/admin/.cache/huggingface` | 约 3.2 GB | Hugging Face 默认读取；可显式设置 `HF_HOME=/Users/admin/.cache/huggingface`，验证时加 `HF_HUB_OFFLINE=1` | 不需要 |
| MinerU pipeline snapshot | 约 1.2 GB（计入 HF cache） | 保留 `/Users/admin/mineru.json`；更严格的离线运行可设置 `MINERU_TOOLS_CONFIG_JSON=/Users/admin/mineru.json` 与 `MINERU_MODEL_SOURCE=local` | 不需要 |
| RapidOCR ONNX package data | 约 31 MB | 随 RapidOCR wheel 安装；不能把旧 `.venv/site-packages` 当共享运行目录 | 无独立模型下载；包安装会重新物化 package data |
| `/Users/admin/.cache/modelscope` | 约 64 MB | 当前生产闭包没有证据要求使用它 | 不纳入计划 |

### 6.3 当前下载计划

```text
显式模型下载：0
```

生产必需模型目前均有现存落点。后续即使获准创建新 Python 环境，也应先在 offline 模式做
cache-only preflight；只有某个生产必需 artifact 经路径和完整性检查确认不存在，才单独列出下载项，
不得用“首次运行自动下载”代替审计。

## 7. 独立环境结论

只有下列三个 Provider 同时满足“生产依赖”和“已有 subprocess worker 隔离设计”：

```text
docling_local
mineru_local
marker_local
```

因此它们在未来获批安装时，各自使用新的 V2 隔离环境是有依据的，不是机械复制旧目录。
RapidOCR 与两种 Paddle Provider 当前是进程内 adapter；它们应作为可选 Provider 依赖安装在
运行 PDFFast Core 的 Provider host 环境中，不应加入最小 `PDFFast Core` 基础依赖。

`pp_structure_v3_light`、独立 `surya_local`、Tesseract 和 generic CLI 不创建环境。

## 8. 发现的生产配置问题

### 8.1 `configs/providers.json` 仍不是严格闭包

该文件由旧 benchmark registry 裁剪而来，仍包含未被 runtime 引用的
`pp_structure_v3_light`。因此“文件在 production 目录”不能作为安装依据。

建议在 Phase 3 后续变更中二选一：

1. 把 production config 收敛到上述 6 个实例；或
2. 明确拆分 benchmark catalog 与 production provider registry。

在完成该变更前，安装逻辑必须使用本审计闭包，而不能遍历 `configs/providers.json` 全量安装。

### 8.2 `enabled` 的旧语义与 V2 Registry 冲突

旧 `stage9_providers_v011.json` 中 `mineru_local`、`marker_local` 为 `enabled:false`。
旧 Stage 9.3 的语义是：`enabled` 只控制“未显式指定 Provider 时”的 benchmark 默认选择；
Stage 9.8 使用 `--providers <name>` 显式调用，因此仍能执行冻结生产链。

当前 V2 `ProviderRegistry.create()` 把 `enabled:false` 解释为“生产禁止调用”，会拒绝合法的
MinerU/Marker policy chain。这是必须在真实 Provider 验证前修正的配置/语义问题；
不能通过安装包或把测试跳过来规避。

建议将以下概念拆开：

```text
benchmark_default_enabled
production_allowed
installed / preflight_available
```

## 9. PDFFast Core 与未来 HTTP Service 边界

Phase 3 只迁移解析 Core。当前 `pyproject.toml` 没有 FastAPI、Uvicorn 或 Starlette 依赖，
应继续保持以下依赖方向：

```text
HTTP / FastAPI Service adapter
  -> 调用稳定的 PDFFast Core application API
  -> 映射 request / job / response / health / observability

PDFFast Core
  -> pipeline context + artifact paths
  -> native parse / quality gate / fallback policy
  -> Provider registry + executor
  -> 不 import FastAPI，不读取 HTTP request，不管理 Web 生命周期
```

未来增加薄 service adapter 时，应通过一个明确的 Core 入口传入输入文件、配置、输出目录、
Provider registry 和 observability sink；Pipeline 不应为 HTTP 层修改业务语义。

## 10. 后续建议（本次不执行）

1. 先修正 production provider registry 的闭包和 `enabled` 语义；
2. 从默认 registry 移除或隔离 `pp_structure_v3_light`，但可保留其 benchmark 历史；
3. 为 6 个生产 Provider 建立 cache-only/offline preflight；
4. 再提交一张仅含 Python package 安装与新环境创建的确认清单；
5. 安装获批后先复用共享 cache 做单任务 contract，不允许自动下载；
6. 如果 offline contract 报缺少模型，记录确切 artifact、目标路径和大小，再单独进入下载计划。

