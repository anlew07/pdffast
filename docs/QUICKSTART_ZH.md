# PDFFast V3 快速上手

## 前置条件

- Python 3.12+；
- 从仓库根目录运行；
- 使用仓库 `uv.lock` 管理主环境依赖；
- 需要 Provider 增强或锁定生产 Profile 时，准备相应 Runtime 和模型资产；
- 输入 PDF 是调用进程可读取的本地文件。

开发与服务依赖：

```bash
uv sync --locked --extra dev --extra service
```

若主环境要运行 RapidOCR / PaddleOCR：

```bash
uv sync --locked --extra dev --extra service --extra runtime-main
```

Docling、MinerU、Marker Worker 环境由 `runtimes/<provider>/pyproject.toml` 和各自
`uv.lock` 管理。Indra 的安装与模型冻结步骤见
[Provider Runtime 环境说明](PROVIDER_RUNTIME_ENVIRONMENTS.md)。

## 最小调用

```python
from pathlib import Path

from pdffast import PDFFastParser

project_root = Path.cwd()
parser = PDFFastParser(
    project_root=project_root,
    output_root=project_root / "outputs",
    output_mode="minimal",
)

result = parser.parse(
    Path("./合同.pdf"),
    run_id="contract_001",
)

markdown = result.markdown
canonical = result.canonical
audit = result.audit
result_dir = result.artifacts["result_dir"]
```

`project_root` 应显式指向当前 V3 checkout。Provider 相对解释器路径由该根目录解析；
不要依赖个人机器的绝对路径、其他 checkout 或旧虚拟环境。

## 正式结果

调用方通常只需使用：

- `result.markdown`：已渲染 Markdown；
- `result.canonical`：Canonical 对应的 Python 字典；
- `result.audit`：结构、来源和渲染边界审计；
- `result.artifacts`：稳定结果文件路径。

正式结果位于：

```text
outputs/<run_id>/result/
  document.json
  document.md
  audit.json
  manifest.json
```

过程 JSON、Provider 原始输出和诊断事件用于审计、排障及回放，不是同一次 V3 解析的内部
数据总线。正常接入不要从上一次运行的 Stage 目录读取输入，也不要把历史 Benchmark 输出
当作当前任务的输入。

## CLI

```bash
uv run python scripts/run_pipeline.py ./合同.pdf \
  --project-root "$PWD" \
  --output-root ./outputs
```

需要使用生产 Profile 时显式指定：

```bash
uv run python scripts/run_pipeline.py ./合同.pdf \
  --project-root "$PWD" \
  --provider-profile configs/profiles/production.indra-triple.json
```

Profile 与自定义 Provider 配置不能同时指定。Profile、Provider 配置、模型资产身份和预检
失败时应停止执行，不要通过默认配置或旧运行产物绕过。

## Embedded JSON 回执

先按 [Provider Runtime 环境说明](PROVIDER_RUNTIME_ENVIRONMENTS.md)冻结已批准的模型资产并通过预检。以下示例从本地文件计算期望摘要，创建新的私有输出目录并传入唯一 run ID。

```bash
pdf=./合同.pdf
output_root=$(mktemp -d)
run_id=$(.venv/bin/python -c 'from uuid import uuid4; print(uuid4().hex)')
expected_sha256=$(.venv/bin/python - "$pdf" <<'PY'
import hashlib
import sys
from pathlib import Path

with Path(sys.argv[1]).open("rb") as stream:
    print(hashlib.file_digest(stream, "sha256").hexdigest())
PY
)

.venv/bin/python -m scripts.run_pipeline "$pdf" \
  --project-root "$PWD" \
  --provider-profile "$PWD/configs/profiles/production.indra-triple.json" \
  --output-root "$output_root" \
  --run-id "$run_id" \
  --expected-input-sha256 "$expected_sha256"
```

CLI 的 stdout 为版本化 JSON 回执。Python 调用使用锁定 Profile 和 `parse_request()`。JudgeAI 要求完整成功并通过独立验签后才送交评审。字段和退出码见 [JudgeAI Embedded 接入合同](integration/JUDGEAI_EMBEDDED_EXECUTION_CONTRACT_V1.md)。

## 输出模式

`minimal`、`diagnostic` 和 `full` 的区别见[输出模式说明](OUTPUT_MODES_ZH.md)。
输出模式影响公开诊断路径范围，不改变 Provider 选择或解析内容。
