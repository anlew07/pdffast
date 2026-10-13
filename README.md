# PDFFast

PDFFast v3 是本地 PDF 解析工具。通过原生文本与版面证据发现文档结构，按需调用
Provider 恢复内容，输出 Markdown、Canonical JSON 和 Audit。

当前 v3 候选基线位于 [`refactor/v3`](https://github.com/anlew07/pdffast/tree/refactor/v3)。
章节发现不依赖固定申报书模板。正式 Runtime 以 Python 对象传递计算结果，JSON 等
Artifact 用于诊断和回放，不作为同次运行的内部数据总线。

## 环境准备

Python 3.12+。开发和 HTTP 服务依赖可使用：

```bash
uv sync --extra dev --extra service
```

实际解析还需准备生产 Provider 环境与模型，见
[Provider 运行环境说明](docs/PROVIDER_RUNTIME_ENVIRONMENTS.md)。主环境运行 RapidOCR/Paddle，
MinerU、Marker、Docling 使用独立 Worker 环境。上述安装命令不代表模型已经就绪，
也不代表 Linux CPU 离线部署已经完成验收。

## Python 使用

从仓库根目录运行：

```python
from pathlib import Path
from pdffast import PDFFastParser

parser = PDFFastParser(
    project_root=Path.cwd(),
    output_root=Path("outputs"),
    output_mode="minimal",
)
result = parser.parse(Path("document.pdf"), run_id="example_run")
print(result.markdown)
print(result.audit)
```

每次解析使用独立 run_id。稳定结果位于：

```text
outputs/<run_id>/result/
  document.json
  document.md
  audit.json
  manifest.json
```

Manifest 保存输入 PDF 的 SHA-256、字节数及采集状态。它在解析开始时先保存输入记录，
成功后补全结果路径，因此 **Manifest 存在不代表解析完成**。摘要代表扫描前读到的字节，
直接调用者应保持文件在解析期间不变。详见[输入指纹说明](docs/reviews/pdf-input-fingerprint.md)。

## HTTP 服务

```bash
PDFFAST_HOST=127.0.0.1 PDFFAST_PORT=8020 PDFFAST_LOG_MODE=normal \
  uv run python -m pdffast.service
```

- `GET /health`：服务健康检查，不表示所有模型均已实际推理验收。
- `POST /parse`：multipart 上传字段 `file`。
- 响应包含 `schema_version="1.0"`、`run_id`、`markdown`、`canonical`、`audit`。

这里的 1.0 是 HTTP 合同版本，与 PDFFast 产品版本不同。重构以 v3 正确性和 JudgeAI
实际使用的对外接口稳定为约束，不要求与旧产品的内部行为或 Markdown 字节一致。

默认关闭宽限为 30 秒，可在启动前设置 `PDFFAST_SHUTDOWN_GRACE_SECONDS`。

## 日志与诊断

`PDFFAST_LOG_MODE=quiet|normal|debug`，默认 normal：

| 模式 | 控制台 |
|---|---|
| quiet | 解析开始/结束、错误和运行心跳；关闭 Uvicorn 访问日志 |
| normal | 主要阶段、增强规划、关键诊断、错误和运行心跳 |
| debug | 详细阶段、Provider 初始化、任务与尝试日志 |

30 秒心跳表示运行仍在执行，不代表真实进展或解析成功。结构化事件和 Provider
Attempt/Production Manifest 保持完整。normal/quiet 在 MinerU Worker 内降低 Loguru 和
进度条噪声，保留 WARNING、ERROR 和 traceback。

配置在新服务/Worker 启动时生效，不支持修改环境变量后自动更新正在运行的实例。
详见[日志分级报告](docs/reviews/runtime-log-noise-reduction.md)。

`output_mode` 支持 minimal、diagnostic、full；影响公开诊断路径，不改变 Provider 选择
或解析内容。补充脚注证据保留来源、空间关系及顺序不确定性，当前不会自动插入正文。

## 质量边界

Provider 执行 SUCCESS、结果 accepted、HTTP 200 和 Audit PASS 都不能证明 OCR 逐字正确。
复杂扫描页的人名、公式、缺句及正文关系仍可能需要人工核验。已有 case_003 结果及
整改规划见：

- [修复后真实解析核验](docs/reviews/case003-post-mineru-fix-validation.md)
- [质量与证据闭环方案](docs/reviews/case003-quality-remediation-plan.md)

原生 Provider 输出引用可能指向临时材料，尚未实施完整的有界证据留存方案。

## 测试

```bash
uv run pytest -q tests/unit tests/contracts tests/regression
```

Reference-bound 测试需显式指定参考资源：

```bash
PDFFAST_REFERENCE_ROOT=/path/to/reference \
PDFFAST_SAMPLE_PDF=/path/to/sample.pdf \
  uv run pytest -q tests/unit tests/contracts tests/regression
```

参考资源用于测试对照，不是正式解析所需的旧工程依赖。缺少外部条件时会 SKIP；
SKIP 不代表端到端或模型验证通过。不要将 8 个主要真实样本的通过外推为所有 PDF 的质量保证。

## 当前候选基线验证

2026-10-13 提交前回归：完整测试 **459 passed、20 skipped、0 failed**；
reference-bound 全套 **479 passed、0 failed**。本次未重新运行完整 case_003，
真实模型与 HTTP 运行证据见各验收报告。这些结果不代表 OCR 内容逐字准确。

## 更多资料

- [重构收尾审查](docs/reviews/refactor-closeout-audit.md)
- [独立环境与 Git 基线](docs/reviews/v3-independent-environment-and-git-baseline.md)
- [服务退出可靠性](docs/reviews/service-shutdown-reliability.md)
- [Supplemental Evidence 合同](docs/reviews/supplemental-evidence-contract.md)
