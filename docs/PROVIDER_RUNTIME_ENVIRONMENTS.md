# PDFFast V3 Provider Runtime 环境

本文是当前 V3 Provider Runtime 的操作说明。配置源为：

- `configs/providers.json`：Provider 身份、解释器、模型资产和环境变量；
- `pyproject.toml` / `uv.lock`：主环境依赖；
- `runtimes/<provider>/pyproject.toml` / `uv.lock`：隔离 Worker 依赖；
- `scripts/install_indra_runtime.sh`：Indra 独立运行时与模型安装；
- `scripts/freeze_production_assets.py`：Indra / MinerU 本地模型资产身份冻结。

不要从历史报告复制绝对路径、旧 checkout 路径或旧虚拟环境路径。运行时解释器必须由当前
checkout 根目录和 Provider 配置解析。

## 1. Runtime 拓扑

| Provider | 执行边界 | Python 环境 |
|---|---|---|
| RapidOCR | 主进程 | 仓库主环境 `.venv` |
| PaddleOCR 文本 | 主进程 | 仓库主环境 `.venv` |
| PaddleOCR-VL | 主进程 | 仓库主环境 `.venv` |
| Docling | 独立 Worker | `runtimes/docling/.venv` |
| MinerU | 独立 Worker | `runtimes/mineru/.venv` |
| Marker | 独立 Worker / 子进程组 | `runtimes/marker/.venv` |
| Indra | 独立 Worker | `runtimes/indra/.venv` |

配置中的解释器路径均相对项目根目录，不应硬编码到某位开发者的 home 目录。

## 2. 安装 Python 环境

开发和 HTTP 服务：

```bash
uv sync --locked --extra dev --extra service
```

主进程 OCR Provider：

```bash
uv sync --locked --extra dev --extra service --extra runtime-main
```

隔离 Worker：

```bash
uv sync --project runtimes/docling
uv sync --project runtimes/mineru
uv sync --project runtimes/marker
```

Indra：

```bash
bash scripts/install_indra_runtime.sh
```

主环境和隔离 Worker 的 `uv sync` 安装 Python 依赖。Indra 安装脚本还会获取配置的模型 revision；离线目标机应预先准备批准的资产。安装后仍需冻结资产、预检和运行验收。

## 3. 模型资产与缓存

模型文件和第三方缓存不提交到 Git。Provider 配置使用 `${HOME}` 等变量引用用户级缓存，
并通过 `required_artifacts`、`required_artifact_trees`、`required_artifact_manifests`
验证实际运行所需文件。

Indra 和 MinerU 还声明 `model_asset_manifest`。在批准的模型版本安装完成后，使用：

```bash
.venv/bin/python -B scripts/freeze_production_assets.py --root "$PWD"
```

脚本只读取本地模型和配置，不下载、不修改模型文件；它为 Indra / MinerU 生成 SHA-256
及文件身份清单。清单含本机文件身份，属于目标机器的部署产物。换机器、替换模型或重建运行时后，在目标 checkout 重新冻结。

发布前应使用正式 Profile 做完整预检，确认 Profile、Provider 配置、模型资产清单、解释器
和运行环境身份一致。预检失败必须阻止正式解析。JudgeAI 的调用与校验流程见 [Embedded 接入合同](integration/JUDGEAI_EMBEDDED_EXECUTION_CONTRACT_V1.md)。

```bash
.venv/bin/python -m pdffast.preflight \
  --project-root "$PWD" \
  --provider-profile "$PWD/configs/profiles/production.indra-triple.json" \
  --json
```

常规预检验证身份与资产状态。正式发布验收使用 `--verify-assets` 重算冻结模型的摘要；`--probe` 额外调用 Provider 的依赖探测。真实推理验收另用代表性 PDF。

## 4. Marker Worker HOME 隔离

Marker 的 Worker HOME 使用独立 nonce 目录：

```text
${HOME}/Library/Caches/pdffast/marker-workers/${PDFFAST_WORKER_ID}
```

该目录只隔离 Worker 自身 HOME、server sentinel 和临时运行状态；Surya 模型、Hugging Face
缓存和 Datalab 模型仍通过配置中的显式路径共享。不要把 Worker HOME 与模型缓存目录混为一谈。

Worker 的进程组与 sentinel 所有权由 Process Supervision 管理。不要手动删除运行中的 Worker
目录或 sentinel，也不要用宽泛的进程名匹配终止其他 Worker。

## 5. 离线与预检原则

- Provider 解释器必须来自当前 V3 checkout；
- Worker 环境由各自 lock 文件管理；
- 模型路径必须指向已批准的本地缓存或固定 revision；
- 缺失资产必须在 Provider 初始化前报告；
- 离线配置必须阻止意外下载型 fallback；
- 预检、生产解析和身份记录必须使用同一配置快照；
- 不允许通过旧 checkout、旧虚拟环境或历史输出目录补齐当前运行依赖。

真实模型推理、并发资源边界、进程回收和 OCR 内容准确率需要在目标部署环境单独验收。
单元测试、Provider SUCCESS 和 Audit PASS 均不能代替真实 PDF 内容核验。

## 6. 当前配置如何变更

新增或替换 Provider Runtime 时，先审阅对应 `pyproject.toml`、`uv.lock`、Adapter、
Normalizer、Registry、Preflight 和模型资产合同。变更配置后必须重新计算配置身份并执行
治理测试；不要只修改文档中的版本号，也不要把历史安装报告当作当前环境证据。
