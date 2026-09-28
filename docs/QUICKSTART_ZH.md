# 快速上手

## 前置条件

- Python 3.12；
- 项目主环境 `/Users/admin/Workspace/pdffast-v2/.venv`；
- 已按生产配置准备 Provider 环境和现有用户级模型缓存；
- 待解析 PDF 是调用进程可读取的本地文件。

Provider 的包版本、隔离环境和缓存位置见
[Provider 运行环境说明](PROVIDER_RUNTIME_ENVIRONMENTS.md)。不要把旧工程 `.venv` 加入
`PYTHONPATH`，也不要把模型复制进仓库。

## 最小调用

```python
from pathlib import Path

from pdffast import PDFFastParser

parser = PDFFastParser(
    project_root=Path("/Users/admin/Workspace/pdffast-v2"),
    output_root=Path("./outputs"),
)

result = parser.parse(
    Path("./合同.pdf"),
    run_id="contract_20260923_001",
)

markdown = result.markdown
canonical = result.canonical
audit = result.audit
result_dir = result.artifacts["result_dir"]
```

`run_id` 会成为输出子目录名。批处理或服务调用应为每次运行生成唯一且可追踪的 ID，避免多个
任务写入同一目录。`case_id` 可选，用于传递业务侧案例标识；不提供时使用 PDF 文件名。

## 查看结果

调用方通常只需使用：

- `result.markdown`：已渲染 Markdown 文本；
- `result.canonical`：Canonical JSON 对应的 Python 字典；
- `result.audit`：结构边界审计；
- `result.artifacts`：稳定结果文件路径。

旧代码可继续使用 `result["markdown"]`、`result["canonical"]` 和
`result["structure_audit"]`。新接入不要读取 `01_stage1` 等编号目录。

## 切换输出模式

```python
from pdffast import PDFFastParser

parser = PDFFastParser(output_mode="diagnostic")
```

`minimal`、`diagnostic` 和 `full` 的区别见[输出模式说明](OUTPUT_MODES_ZH.md)。模式不会改变
解析内容，只改变返回结果公开的产物路径范围。
