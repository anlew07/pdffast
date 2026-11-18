# PDFFast 快速上手（独立开发）

本文面向**独立 PDFFast 源码仓库**，不使用 JudgeAI 的嵌入式运行时。建议 Python **3.12**、uv、Git。克隆到任意可写目录；`pdffast` 只是推荐的本地文件夹名。

> 安装 Python 包 ≠ 完整模型就绪。第一次完整解析之前，先按 [环境重建说明](REBUILD_ZH.md)准备 Provider、权重与用户级缓存。完全清空模型缓存的机器不能假定离线可用。

## 1. 克隆并安装主开发环境

```bash
git clone https://github.com/anlew07/pdffast.git pdffast
cd pdffast
git status --short
uv python install 3.12
uv sync --frozen --python 3.12 --extra dev --extra service --extra runtime-main
.venv/bin/python --version
.venv/bin/python -c "from pdffast import PDFFastParser; print('PDFFast import OK')"
```

上述命令安装 Core、开发测试、可选 HTTP 服务及主环境的 RapidOCR/Paddle 依赖。它们**不安装** MinerU、Marker、Docling 的独立虚拟环境，也不下载 Indra OCR 权重。

只做代码级检查时：

```bash
.venv/bin/python -m pytest -q tests/unit
.venv/bin/python -m pytest -q tests/contracts
```

部分测试可能因为外部模型、文件或可选依赖被跳过；应记录实际 PASS / SKIP 数。参考样本专项测试不能靠旧目录残留来“隐式通过”。

## 2. 为完整 Provider 环境准备独立 Worker

```bash
uv sync --frozen --python 3.12 --project runtimes/mineru
uv sync --frozen --python 3.12 --project runtimes/marker
uv sync --frozen --python 3.12 --project runtimes/docling
```

Provider 依赖与模型文件是两件事。必要的用户级缓存可能在 `~/.paddlex`、`~/.cache/huggingface`、`~/mineru.json`、Marker 的独立缓存目录；具体路径以**当前** `configs/providers.json` 为准。

Indra 是显式注册的可选 OCR 路径，单独安装：

```bash
# 首次安装需要访问模型仓库；正式可复现部署应固定批准过的模型 commit SHA
INDRA_MODEL_REVISION="YOUR_APPROVED_HF_COMMIT_SHA" \
  bash scripts/install_indra_runtime.sh

.venv/bin/python scripts/verify_indra_runtime.py --hashes --preflight
```

不要直接照抄 `YOUR_APPROVED_HF_COMMIT_SHA` 占位符；应使用经核对的实际 Hugging Face 模型提交 SHA。模型授权需独立审查，见 [Indra 文档](indra_runtime.md)。

## 3. 解析一份真实 PDF

仅在相应候选链依赖和权重就绪后运行：

```bash
.venv/bin/python scripts/run_pipeline.py /absolute/path/to/sample.pdf \
  --project-root . --output-root outputs --run-id smoke_001
```

结果在：

```text
outputs/smoke_001/result/
  document.md
  document.json
  audit.json
  manifest.json
```

审计通过不意味着 OCR 文字或表格全部正确；应对关键中文字段、数字、表格与来源证据人工核对。

若需要测试 Indra 候选三模型路由，必须**显式**指定：

```bash
.venv/bin/python scripts/run_pipeline.py /absolute/path/to/sample.pdf \
  --project-root . --output-root outputs --run-id indra_001 \
  --provider-profile configs/profiles/production.indra-triple.json
```

不指定 `--provider-profile` 时不会自动切换成 Indra 路由；请不要把两种测试混为一谈。

## 4. Python API / 可选 HTTP 服务

```python
from pathlib import Path
from pdffast import PDFFastParser

parser = PDFFastParser(
    project_root=Path.cwd(),
    output_root=Path("outputs"),
    output_mode="minimal",
)
result = parser.parse(Path("/absolute/path/to/sample.pdf"), run_id="python_001")
print(result.artifacts["result_markdown"])
print(result.audit)
```

```bash
PDFFAST_HOST=127.0.0.1 PDFFAST_PORT=8020 \
  .venv/bin/python -m pdffast.service
```

`GET /health` 只说明服务入口可访问，不代表模型齐备。HTTP `POST /parse` 使用 multipart `file`。接口与返回合同参见 [集成说明](INTEGRATION_ZH.md)。

## 5. 遇到安装/解析失败

先记录 `git rev-parse HEAD`、Python 版本、所用 Profile、完整报错和本次 `run_id`，参考 [故障排查](TROUBLESHOOTING_ZH.md)与[维护者手册](MAINTENANCE_ZH.md)。如果准备删除旧环境并彻底重建，请**先**走 [环境重建门禁](REBUILD_ZH.md)，不要把 JudgeAI 的 `.runtime/pdffast` 当作开发仓库。
