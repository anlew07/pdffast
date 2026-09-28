# 输出模式说明

PDFFast 的 `output_mode` 只控制调用方能看到哪些产物路径，不改变解析算法、质量阈值、
Provider escalation 顺序或 Frozen route。无论选择哪种模式，稳定业务结果都写入本次运行的
`result/` 目录。

## 三种模式

| 模式 | 适用场景 | `result.artifacts` 公开内容 |
|---|---|---|
| `minimal` | 日常业务调用、批处理、服务接入 | 仅 `result/` 下的稳定结果 |
| `diagnostic` | 联调、偶发失败定位、Provider 排查 | 稳定结果及 `pipeline_log` |
| `full` | 迁移回归、算法调试、完整证据审查 | 稳定结果、日志和全部旧 Stage 路径 |

默认模式是 `minimal`。推荐业务系统只依赖以下稳定键：

```text
result_dir
result_document
result_markdown
result_audit
result_manifest
```

`diagnostic` 额外公开 `pipeline_log`。`full` 还会公开 `profile`、`quality_gate`、
`runtime_policy`、`production_manifest` 等内部路径；这些字段用于诊断，不属于长期业务契约。

## 目录结构

```text
<output_root>/<run_id>/
  result/
    document.json              # Canonical 结构化结果
    document.md                # 面向阅读和下游 LLM 的 Markdown
    audit.json                 # 结构边界审计
    manifest.json              # 本次公开结果索引
  diagnostics/
    logs/
      pipeline.log             # Stage、Provider stdout/stderr 和 Python 日志
  01_stage1/ ... 10_2_1/       # 内部兼容产物
```

第一版在所有模式下都保留内部 Stage 文件。`minimal` 的含义是“不向公共结果 mapping 暴露”，
不是删除文件；这保证历史回归、失败复盘和 Provider 证据链仍可使用。

## 使用方式

```python
from pathlib import Path

from pdffast import PDFFastParser

parser = PDFFastParser(
    output_root=Path("./outputs"),
    output_mode="diagnostic",
)
result = parser.parse(Path("./document.pdf"), run_id="case_001")

print(result.artifacts["result_markdown"])
print(result.artifacts["pipeline_log"])
```

若要临时让 Stage 输出直接显示在当前终端，可设置 `capture_output=False`。业务运行不建议关闭
捕获，否则旧 Stage 和第三方 Provider 的输出可能干扰调用进程日志。

## 失败定位

解析失败会抛出 `ParseExecutionError`，其 `run_dir` 指向本次运行目录，`log_path` 指向
`diagnostics/logs/pipeline.log`。日志记录失败前已经产生的 Stage/Provider 输出；Python 异常链
仍通过 `raise ... from ...` 保留，调用方可使用标准异常日志记录 traceback。

日常生产建议使用 `minimal`；需要持续收集内部日志路径时使用 `diagnostic`；只有排查解析逻辑
或执行 reference-bound 回归时才使用 `full`。
