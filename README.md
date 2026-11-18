# PDFFast

**PDFFast** 是一个以原生 PDF 内容为优先、按需使用 OCR/版面 Provider 补全信息的 Python PDF 解析项目。核心流水线生成可供阅读与下游程序使用的 **Markdown、Canonical JSON、结构审计（Audit）与输入 Manifest**。

- GitHub 仓库：`anlew07/pdffast`；Python 包与导入名：`pdffast`。
- 正式开发分支：`main`。本地目录建议叫 `pdffast`，不再以 `pdffast-v2`、`pdffast-v3` 命名新开发工作区。
- **V3** 在部分旧设计文档和源码中表示架构演进阶段，不是另一个仓库，也不能当作当前发布版本号。发布版本以 Git Tag 与 `pyproject.toml` 为准。
- 当前工作重点：**稳定维护、Bug 修复、模型/Provider 可控更新、可复现的质量回归**；非必要不做大规模结构重构。

> 核心代码可从 Git 克隆，但完整 OCR 环境 **不能仅靠克隆源码得到**。权重、用户级缓存、授权与外部测试资料需单独准备。请在清理旧工作区前阅读 [环境重建与安全清理](docs/REBUILD_ZH.md)。

## 从这里开始

| 我想做什么 | 阅读 |
|---|---|
| 新克隆项目、运行基本测试、解析一份 PDF | [快速上手](docs/QUICKSTART_ZH.md) |
| 在新机器上准备 Provider、模型与验收环境 | [环境重建与安全清理](docs/REBUILD_ZH.md) |
| 定位 Bug、调整 OCR、回归与合并 | [维护者手册](docs/MAINTENANCE_ZH.md) |
| 让 AI/新开发者快速理解源码与约束 | [AGENTS.md](AGENTS.md) |
| 查找现行文档与历史实验记录 | [文档索引](docs/INDEX.md) |
| 管理项目名称、提交、版本和 JudgeAI 锁定版本 | [版本管理规范](docs/VERSIONING_ZH.md) |

## 运行轮廓

```text
PDF
  → Native 原生文本/结构
  → Evidence 与 Quality Gate
  → Fallback Planning / Capability Routing / Policy
  → Provider Executor（按需 OCR、版面解析及候选回退）
  → Canonical Builder → Markdown Renderer → Audit
  → ParseResult + result/document.md / document.json / audit.json / manifest.json
```

主入口是 `pdffast.PDFFastParser.parse()`，CLI 是 `scripts/run_pipeline.py`。HTTP 服务是可选适配层，不属于 Core 的依赖。

源码中的 Stage 编号和历史 Artifact 文件名是兼容标识；**同一次解析的核心数据以 Python 对象传递，不能把旧 Stage JSON 重新设计成内部数据总线**。

## 开发环境的最小起点

建议 Python **3.12**，使用 [uv](https://docs.astral.sh/uv/)：

```bash
git clone https://github.com/anlew07/pdffast.git pdffast
cd pdffast
uv python install 3.12
uv sync --frozen --python 3.12 --extra dev --extra service --extra runtime-main
.venv/bin/python -m pytest -q tests/unit
```

上面仅为**主 Python 环境与代码测试入口**，不等于 MinerU/Marker/Docling/Indra 模型已安装，也不表示真实 PDF 可完成全链路解析。安装其他 Worker、模型与验证步骤参见 [快速上手](docs/QUICKSTART_ZH.md)和[环境重建](docs/REBUILD_ZH.md)。

模型与缓存准备完成后，可独立解析：

```bash
.venv/bin/python scripts/run_pipeline.py /absolute/path/to/sample.pdf \
  --project-root . --output-root outputs --run-id smoke_local
```

稳定产物写入 `outputs/smoke_local/result/`。不指定 Profile 时维持既有默认候选路由；显式选择 `configs/profiles/production.indra-triple.json` 才会使用 Indra 三模型候选链。

## 扩展和集成

- 当前内置生产 Provider：RapidOCR、PaddleOCR 文本、PaddleOCR-VL、MinerU、Marker、Docling；另有通过插件注册的 **Indra OCR**，需独立隔离环境。MiniCPM-OCR 为可选研究/评测方向，不默认启用。
- Provider 的注册、选择、执行和 Canonical Normalizer 分层；不要将新 Provider 的推理逻辑写进 Core Pipeline。
- Provider `SUCCESS`、Audit `PASS`、HTTP 200 **不等于 OCR 逐字准确**。业务关键数字、中文标识、表格与阅读顺序仍需人工或 GT 对照。
- JudgeAI 使用自己的 PDFFast Git Commit 锁与隔离运行时；更新此仓库 **不会自动更新 JudgeAI**。见 [Python 集成](docs/INTEGRATION_ZH.md)。

更多内容请使用 [文档索引](docs/INDEX.md)。历史 V2/V3 的实验、评估和重构记录保留为来源证据，不作为今天的新装机指令。
