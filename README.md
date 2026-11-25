# PDFFast

PDFFast V3 是本地 PDF 解析工具。通过原生文本与版面证据发现文档结构，按需调用
Provider 恢复内容，输出 Markdown、Canonical JSON 和 Audit。章节发现不依赖固定申报书模板。

V3 正式 Runtime 由 Pipeline 统一编排，通过 Python 对象传递 Native、Evidence、Quality、
Fallback 和 Canonical 等计算结果。JSON、Provider 文件和结构化事件用于诊断、审计与回放，
**不作为同次运行的内部数据总线**。源码中的部分 Stage 编号是内部兼容标识，不代表恢复了
旧版文件串联架构。

当前 V3 主线为 [main](https://github.com/anlew07/pdffast/tree/main)。
JudgeAI 通过锁定的 Git 提交部署 PDFFast；本仓库的新提交不会自动改变已部署版本。
升级需由 JudgeAI 明确更新锁定版本并重新进行解析与接口回归验收。

## 文档入口

- [V3 快速上手](docs/QUICKSTART_ZH.md)
- [V3 架构](docs/ARCHITECTURE.md)
- [V3 Pipeline](docs/PIPELINE.md)
- [Provider Runtime 环境与安装](docs/PROVIDER_RUNTIME_ENVIRONMENTS.md)
- [Provider 插件接入](docs/PROVIDER_PLUGINS_ZH.md)
- [输出模式](docs/OUTPUT_MODES_ZH.md)
- [生产解析身份合同](docs/contracts/production_parser_identity_v1.md)
- [JudgeAI Embedded 接入合同](docs/integration/JUDGEAI_EMBEDDED_EXECUTION_CONTRACT_V1.md)
- [部署恢复合同](docs/contracts/deployment_control_v1.md)
- [文档索引与历史报告说明](docs/README.md)

## 环境准备

Python 3.12+，使用仓库锁文件管理依赖。开发与服务依赖：

```bash
uv sync --extra dev --extra service
```

若当前主环境需要执行 RapidOCR / PaddleOCR Provider，再安装主环境 OCR 依赖：

```bash
uv sync --extra runtime-main
```

Docling、MinerU、Marker 使用仓库内独立 Worker Runtime：

```bash
uv sync --project runtimes/docling
uv sync --project runtimes/mineru
uv sync --project runtimes/marker
```

Indra 使用独立安装脚本与模型版本清单，见
[Provider Runtime 环境说明](docs/PROVIDER_RUNTIME_ENVIRONMENTS.md)。

以上命令只管理 Python 依赖，不代表模型资产已就绪，也不代表真实 PDF 解析已验收。
模型和外部缓存不提交到 Git。

## Provider 可插拔

默认生产 Provider 集合与候选顺序由冻结策略管理。新引擎通过本地显式注册启用，不自动扫描
第三方插件，也不会自动进入 JudgeAI 已锁定的生产版本。

新增 Provider 需要实现 Adapter、Normalizer，并在可信的 `configs/providers.json` 中显式声明
插件和 Provider 配置；完成合同测试、预检和真实样本验证后，才可通过 Profile 或候选链配置
参与生产路由。MiniCPM-OCR 是独立 Benchmark 候选，不进入默认生产路由。

**引擎注册成功不代表内容准确、性能合格或生产准入。** 解析前仍需验证 Provider 环境、
模型资产、配置身份与候选闭包。

## Python 使用

从仓库根目录运行：

```python
from pathlib import Path

from pdffast import PDFFastParser

project_root = Path.cwd()
parser = PDFFastParser(
    project_root=project_root,
    output_root=project_root / "outputs",
    output_mode="minimal",
)
result = parser.parse(Path("document.pdf"), run_id="example_run")
print(result.markdown)
print(result.audit)
```

每次解析使用独立 `run_id`。稳定结果位于：

```text
outputs/<run_id>/result/
  document.json
  document.md
  audit.json
  manifest.json
```

Manifest 保存输入 PDF 的 SHA-256、字节数及采集状态。Manifest 存在不代表解析完成；
应以最终状态、结果文件和 Audit 为准。

## HTTP 服务

安装 service extra 后可运行：

```bash
PDFFAST_HOST=127.0.0.1 PDFFAST_PORT=8020 PDFFAST_LOG_MODE=normal \
  uv run python -m pdffast.service
```

- `GET /health`：服务健康检查，不表示所有模型均已实际推理验收。
- `POST /parse`：multipart 上传字段 `file`。
- 响应包含 HTTP 合同版本、`run_id`、`markdown`、`canonical` 和 `audit`。

## 测试

默认测试只包含可重复的当前 V3 单元与合同测试，不依赖旧工程目录、历史运行输出或真实模型：

```bash
uv run pytest -q
```

需要真实 PDF 样本的回归测试单独运行。测试数据根目录应包含
`benchmark/samples/real/case_003.pdf` 等样本：

```bash
PDFFAST_TEST_DATA_ROOT=/path/to/test-data \
  uv run pytest -q -m regression
```

依赖既有 case_003 / case_004 产物的回归测试还需要设置
`PDFFAST_REGRESSION_ARTIFACTS_ROOT`，其目录下可包含
`final_structure_regression/case_002`、`case_003`、`case_004`，
`template_removal_review/case_003`、`case_004`，以及
`mineru_case003_pages43_44_validation/run_3fe3efd98b/page_43` 至 `page_46`。

V2 → V3 的历史迁移对照测试已隔离到 `tests/migration`，不参与默认测试。只有需要复核历史迁移
时才运行：

```bash
PDFFAST_REFERENCE_ROOT=/path/to/read-only-v2 \
PDFFAST_SAMPLE_PDF=/path/to/case_002.pdf \
  uv run pytest -q -m migration
```

历史迁移测试需要只读旧工程和对应样本；它们不是 V3 运行时依赖，也不作为当前默认 CI 的
通过依据。缺少真实样本、模型或历史数据时，相关专项不运行；SKIP 不代表端到端或内容质量验收通过。

CI 对应提交的结果是当前代码测试状态的唯一依据。历史报告中的测试数量、机器路径和环境
版本只代表报告日期，不应当作当前 HEAD 的验证证据。

## 质量边界

Provider 执行 SUCCESS、结果 accepted、HTTP 200 和 Audit PASS 都不能证明 OCR 逐字正确。
复杂扫描页的人名、公式、缺句及正文关系仍可能需要人工核验。内容准确率必须通过带
Ground Truth 的 PDF Benchmark 单独量化。
