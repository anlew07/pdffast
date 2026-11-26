# JudgeAI Embedded Execution Contract V1

本文件定义 JudgeAI 调用本地 PDFFast、接收回执和验证交付物的接口。Embedded V1 自 [PR #9 合并提交](https://github.com/anlew07/pdffast/commit/1bc1b9149718d23497845a61ade914f9a333da2e) 起可在 PDFFast `main` 使用。发布前的实测记录见 [B06-A5](../../B06-A5_REAL_PDF_ACCEPTANCE.md)。

## 部署前置条件

固定通过验收的 PDFFast Git 提交，在目标机器上准备既有 Provider Runtime 和批准的模型。Indra 和 MinerU 资产清单由部署者在目标机器上使用仓库冻结脚本生成。清单包含本机文件身份，需随部署环境重新生成。见 [Provider Runtime 环境](../PROVIDER_RUNTIME_ENVIRONMENTS.md)。

在 PDFFast checkout 根目录先确认锁定 Profile 通过预检。

```bash
.venv/bin/python -m pdffast.preflight \
  --project-root "$PWD" \
  --provider-profile "$PWD/configs/profiles/production.indra-triple.json" \
  --json
```

预检通过后，使用相同 checkout、Profile 和 Python 环境启动 Embedded CLI。JudgeAI 升级时要重新核对部署身份并完成真实项目联调。采用 macOS 受管模式时，还需运行 [部署 Health](../contracts/deployment_control_v1.md) 并验收 Worker 调用、恢复和取消。

## 调用

JudgeAI 在提交前计算原始 PDF 的 SHA-256 并分配一次性 `run_id`。调用期间保持输入文件不变。部署者应使用私有输出根目录，并保证本次 run 仅由受管 PDFFast 进程写入。部署端提供本地 PDF 路径、输出根目录和锁定 Production Profile。每次新执行使用新的 run_id，PDFFast 独占保留 `output_root/run_id`。

请求采用 [Request Schema](../contracts/embedded_execution_request.v1.schema.json)。下面的摘要是示例值，调用时传入原始 PDF 的实际摘要。

```json
{
  "schema_version": "pdffast.execution.request.v1",
  "run_id": "judge-task-001",
  "input": {
    "sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
  },
  "options": {}
}
```

`run_id` 长度为 1 至 128 字符，首字符为 ASCII 字母、数字或下划线，后续可使用 ASCII 字母、数字、下划线、短横线和点。V1 的 options 为空对象。

从 PDFFast checkout 根目录运行。下例的变量来自 JudgeAI 已准备的任务、私有输出根目录和提交前的 PDF 摘要。

```bash
.venv/bin/python -m scripts.run_pipeline "$pdf" \
  --project-root "$PWD" \
  --provider-profile "$PWD/configs/profiles/production.indra-triple.json" \
  --output-root "$output_root" \
  --run-id "$run_id" \
  --expected-input-sha256 "$expected_sha256"
```

PDF 是位置参数。`--expected-input-sha256` 启用 Embedded JSON 模式。正常处理完成时 stdout 只写一份 JSON。部署者负责访问控制 stderr 和运行目录中的本机诊断日志。父进程按退出码、JSON Schema 和执行身份联合验证回执。命令行语法错误可能在解析参数时仅产生 stderr 和退出码；调用方应把它当作调用配置错误。

Python 入口为 `PDFFastParser(...).parse_request(pdf_path, request)`。成功或部分成功时读取 `ParseResult.execution_contract`。对 `PDFFastError` 和从 `pdffast.runtime` 导入的 `ParseCancelledError` 调用 `to_contract()`。生产 Profile、项目根目录和输出根目录通过 Parser 构造配置传递。

## 响应

[结果 Schema](../contracts/embedded_execution.v1.schema.json) 定义 `pdffast.execution.v1`。进行离线 Schema 校验时以 `$id` 注册 Request Schema，再解析结果 Schema 的本地引用。

| 字段 | 用途 |
| --- | --- |
| `run_id`、`request`、`status` | 关联原始请求、同次执行和结果状态 |
| `input.sha256`、`input.byte_size` | 实际读取的 PDF 身份 |
| `result.document`、`result.markdown`、`result.audit`、`result.manifest` | Canonical、Markdown、Audit 及根 Manifest 的 run-relative 路径 |
| `execution.provider_runtime` | 可用 Provider 的运行时身份、包版本与模型版本或资产摘要 |
| `execution.attempted_provider_counts`、`selected_provider_counts`、`execution_evidence` | 实际 Provider 及任务顺序、候选链、回退和选中证据 |
| `execution.effective_config_fingerprint`、`source_sha256`、`source_dirty`、`algorithm_sha256` | 有效配置与源码身份 |
| `artifacts` | 每个证据文件的相对路径、字节数和 SHA-256 |
| `warnings`、`risk_flags`、`error` | 当次运行的警告和风险。结果回执的 error 为 null。 |

[错误 Schema](../contracts/embedded_execution_error.v1.schema.json) 定义 `pdffast.execution.error.v1`。程序使用 `error.code`、`error.stage` 和 `retryable`。有效 run_id 会随错误保留。Provider 初始化异常包含实际 Provider、相关任务、初始化状态及异常类型。根 Manifest 仅随可交付结果发布。

## 验证与处理

JudgeAI 收到子进程回执后，先关联本次 `run_id` 和原请求。验证 Schema 后，从受信任的输出根目录定位 run，拒绝绝对路径、越界路径和符号链接。用下列等式验证实际字节。

```text
JudgeAI 重新读取原始 PDF 的 SHA-256
  == 请求 input.sha256
  == PDFFast Execution Contract input.sha256
  == result/manifest.json input.sha256

实际 Markdown SHA-256 == artifacts 中 markdown.sha256
实际 Canonical、Audit、Production Manifest 及其他证据 SHA-256
  == 各自的 artifacts 文件摘要
```

根 Manifest 中的 Execution Contract 应与 stdout 回执相同。单独计算并保存根 Manifest 的 SHA-256，其嵌套的产物清单不包含自身摘要。校验每个产物的字节数和 SHA-256，读取内容时沿用已核验的字节。现有内部产物中的绝对定位字段只供 PDFFast 本机运维使用，JudgeAI 使用外部合同提供的 run-relative 路径。任何身份、摘要、路径或 Audit 校验失败都必须阻断 LLM 评审。

| 状态 | 退出码 | JudgeAI 处理 |
| --- | --- | --- |
| `SUCCESS` | 0 | 核验身份、Audit 和全部产物后交给评审 |
| `PARTIAL_SUCCESS` | 4 | 保存可用文档和未解决证据，转人工处理 |
| `BLOCKED` | 2 | 保存错误码，按请求、输入或环境原因处置 |
| `FAILED` | 3 | 保存错误与诊断引用，停止评审 |
| `CANCELLED` | 5 | 保存协作取消状态，停止评审 |
| `INTERRUPTED` | 由父进程判定 | 异常退出且缺少可确认的最终回执时，结合 OS 退出信息及受管任务回执协调 |

普通 Python 执行错误返回 `FAILED`。只有父进程能在无可靠终态时判定 `INTERRUPTED`。受管调用持久化 `core_run_id` 与 `job_id` 的关联。同一次执行用原 `JOB_ID` 恢复。主动重跑分配新的 run ID 和 Job ID。部署回执中的历史 `run_id` 字段承载 Job ID。

## 责任边界

PDFFast 管理 Indra、RapidOCR 和 MinerU 的选择条件、优先级、回退链及 Quality Gate。JudgeAI 负责提交 PDF、提供身份、保存和检验结果，并在门禁通过后提交 Markdown。当前独立 HTTP 服务使用自己的响应合同。
