# PDFFast v2

PDFFast v2 是一个面向中文 PDF 的本地解析工具。项目将已验证的多阶段解析流程整理为
清晰的 Python 工具架构，对业务调用方提供稳定的 `PDFFastParser.parse(pdf_path)` 接口，
内部仍保留质量门、按需 Provider 升级和结构审计能力。

当前工程只提供解析 Core，不依赖 FastAPI、`UploadFile`、HTTP 请求对象或 Celery。后续可以
在 Core 外增加轻量 service adapter，而无需修改解析 Pipeline。

## 快速使用

生产 Provider 环境及用户级模型缓存需按
[Provider 运行环境说明](docs/PROVIDER_RUNTIME_ENVIRONMENTS.md)准备。已有模型缓存会原地复用，
PDFFast 不会为了运行示例主动下载模型。

```python
from pathlib import Path

from pdffast import PDFFastParser

parser = PDFFastParser(
    project_root=Path("/Users/admin/Workspace/pdffast-v2"),
    output_root=Path("./outputs"),
    output_mode="minimal",
)

result = parser.parse(
    Path("./document.pdf"),
    run_id="business_20260923_001",
)

print(result.markdown)
print(result.artifacts["result_markdown"])
```

解析成功后，稳定结果位于：

```text
outputs/business_20260923_001/result/
  document.json
  document.md
  audit.json
  manifest.json
```

旧式 mapping 访问仍可用于迁移，例如 `result["markdown"]` 和
`result["structure_audit"]`；新代码建议使用 `result.markdown`、`result.canonical`、
`result.audit` 和 `result.artifacts`。

## 输出模式

`output_mode` 支持三种模式：

- `minimal`：默认值，只向调用方公开稳定的 `result/` 路径。
- `diagnostic`：在稳定结果之外公开 `pipeline_log`，适合日常问题定位。
- `full`：公开全部旧 Stage 产物路径，适合迁移回归和深度排查。

三种模式都不会改变算法、Provider 顺序或解析结果。第一版也不会删除内部 Stage 文件，
避免影响失败排查和历史回归。详细说明见
[输出模式说明](docs/OUTPUT_MODES_ZH.md)。

## 工程边界

```text
业务系统 / HTTP adapter
  -> PDFFastParser
  -> Core Pipeline
  -> Provider Registry / 隔离 worker
  -> ParseResult + result/
```

业务系统不应直接导入 `pdffast.native`、`pdffast.fallback` 或编号 Stage 目录。Provider 是
运行时能力：主环境承载 RapidOCR 和 Paddle，MinerU、Marker、Docling 使用各自的子进程环境。
模型位于用户级共享缓存，不复制进 Git 仓库，也不引用旧项目 `.venv`。

更多资料：

- [快速上手](docs/QUICKSTART_ZH.md)
- [Python 系统接入](docs/INTEGRATION_ZH.md)
- [常见问题排查](docs/TROUBLESHOOTING_ZH.md)
- [项目架构](docs/ARCHITECTURE.md)
- [Core Pipeline](docs/PIPELINE.md)
- [迁移计划](docs/MIGRATION_PLAN.md)

## 测试

使用项目自己的虚拟环境运行默认测试：

```bash
./.venv/bin/pytest -q tests/unit tests/contracts tests/regression
```

需要旧工程和真实样本的 reference-bound 回归测试必须显式提供路径：

```bash
PDFFAST_REFERENCE_ROOT=/Users/admin/Workspace/pdffast \
PDFFAST_SAMPLE_PDF=/absolute/path/to/sample.pdf \
  ./.venv/bin/pytest -q tests/regression/test_phase2_pipeline_parity.py
```

外部前置条件缺失时相关测试会显示 `SKIP`；`SKIP` 不代表真实 Provider 或端到端解析通过。
