# B06-A2 结构化错误与状态

## 对外结果

| 状态 | 触发条件 | Embedded CLI 退出码 |
| --- | --- | --- |
| `SUCCESS` | 必需产物生成、Audit 通过，任务无失败或终态保留 | 0 |
| `PARTIAL_SUCCESS` | Audit 通过且交付可用内容，已有策略为部分任务保留源证据 | 4 |
| `BLOCKED` | 请求、输入、生产预检或 run 目录预留未通过 | 2 |
| `FAILED` | Core 执行异常、Audit 失败、无可用结果或发布失败 | 3 |
| `CANCELLED` | 执行检测到明确的协作取消请求 | 5 |
| `INTERRUPTED` | 父进程发现异常退出，且无法确认有效最终回执 | 由父进程结合 POSIX 退出信号和受管任务回执判定 |

`PDFFastParser.parse_request()` 保留 Python 异常接口。类型化异常的 `to_contract()` 可序列化为 Error Schema。现有 CLI 在收到 `--expected-input-sha256` 时走同一版本化入口，标准输出仅含一份 JSON。普通 Python 异常保持 `FAILED`。

## 调用链与关键证据

- ParseService 在加载 Profile 或预留输出目录前拦截非法请求、不可读或空 PDF 和摘要不符。有效 run_id 随异常保留。
- 锁定 Core 持有本次 Observer 对象并读取实际异常阶段。Provider 初始化诊断包含名称、相关任务 ID、初始化开始与成功状态、异常类型。Fallback Executor 只向原 Observer 补充任务 ID，Provider 选择、任务尝试、关闭和回退照旧。
- 任务链耗尽且无策略允许的终态保留时，现有 Canonical 门禁拒绝构建有效结果。Core 返回 `PROVIDER_EXECUTION_FAILED` 并提供失败任务统计。通过 Audit 的终态保留仍须包含可用内容，只有占位符返回 `NO_USABLE_RESULT`。
- 失败合同仅序列化固定消息、结构化证据和 run-relative 诊断路径。完整 Preflight 报告、异常字符串和详细日志保留给本机运维。已有锁定 Manifest 原子发布保持有效，失败和取消路径不会发布成功 Manifest。
- 主要修改位于 `pdffast/errors.py`、`runtime.py`、`ParseService`、`pipeline/runner.py`、`fallback/executor.py` 的观测调用、`scripts/run_pipeline.py` 和错误 Schema。

## 验证

`test_parser_provenance.py` 和 `test_cli_log_output.py` 共 **25 项通过**。覆盖缺失输入、摘要不符、非法标识和版本化选项、预检错误安全字段、Provider 初始化和任务失败、Audit 失败、协作取消、可用部分结果、占位符拒绝和 CLI JSON 退出码。真实 Provider 通过 Fake Provider 注入，Core、Fallback Executor、Canonical、Renderer 和 Audit 的生产接线均有相应用例。完整离线结果见 A3。
