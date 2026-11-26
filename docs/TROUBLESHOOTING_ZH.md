# 常见问题排查

## 从哪里开始

Embedded 调用先记录 `run_id`、退出码、`error.code`、`error.stage` 和 `diagnostics`。普通 Python 调用记录异常类型、`ParseExecutionError.run_dir` 与 `log_path`。运行已经进入 Core 时，可以检查下面的本机产物。

```text
<run_dir>/diagnostics/logs/pipeline.log
<run_dir>/result/manifest.json
```

`pipeline.log` 包含失败前的 Stage、Provider stdout/stderr 和 Python 日志。完整 traceback 应由
调用方通过 `logger.exception()` 记录，因为 Core 会保留原始异常链。

## Embedded 返回 BLOCKED 或 FAILED

| 错误码 | 检查项 |
| --- | --- |
| `INVALID_CONFIGURATION_OR_REQUEST` | 版本、run ID、options 以及 Parser 或 CLI 的 Profile 参数。 |
| `INPUT_UNAVAILABLE`、`INPUT_SHA256_MISMATCH` | 原始 PDF 可读性、字节数和 SHA-256。输入需在运行期间保持一致。 |
| `PRODUCTION_PREFLIGHT_FAILED` | 用同一 checkout、解释器和 Profile 运行 `python -m pdffast.preflight`，查看 Provider 状态和缺失的本机清单。 |
| `RUN_RESERVATION_FAILED` | 输出根目录权限，或该 run ID 的目录、预留标记已经存在。真正重跑时分配新 run ID。 |
| `PROVIDER_INITIALIZATION_FAILED`、`PROVIDER_EXECUTION_FAILED` | 根据回执中的 Provider、失败阶段和任务标识定位本机日志。 |
| `OUTPUT_VALIDATION_FAILED`、`NO_USABLE_RESULT` | 检查 Audit、渲染诊断和实际正文。该次执行的中间产物只能用于诊断。 |

`PARTIAL_SUCCESS` 包含可用结果和未解决证据，按 [JudgeAI 接入合同](integration/JUDGEAI_EMBEDDED_EXECUTION_CONTRACT_V1.md)转人工处理。受管 Job 的状态恢复和取消见 [部署恢复合同](contracts/deployment_control_v1.md)。

## 终端出现大量 Stage 输出

确认 Parser 没有设置 `capture_output=False`。默认值是 `True`，旧 Stage 的摘要和第三方库输出
会进入 `pipeline.log`。CLI 或业务 adapter 可以打印自己的简洁状态，但不要直接调用内部 Stage。

## 找不到 Provider

先区分两类问题：

- 配置错误：Frozen policy 引用的 Provider 不在 runtime-enabled Registry 中，启动校验会直接失败；
- 运行环境错误：Provider 已启用，但其 Python 包、解释器或模型 artifact 不存在。

普通解析的候选由冻结策略及可信配置决定。锁定生产调用按部署提供的 Profile 检查候选闭包；仓库的 `production.indra-triple.json` 允许 Indra、RapidOCR 和 MinerU。排障时以实际生效的 Profile 与预检报告为准。

## 模型或缓存缺失

PDFFast 的 Python 环境和模型缓存相互独立：

- 主环境使用 `.venv`，隔离 Worker 使用 `runtimes/<provider>/.venv`；
- Paddle/PaddleX 模型复用 `~/.paddlex`；
- Hugging Face 模型复用 `~/.cache/huggingface`；
- Marker 还复用用户级 Datalab cache；
- RapidOCR ONNX 权重随 package 提供。

不要把旧项目 `.venv` 加到解释器路径，不要把模型复制进 Git 仓库，也不要在排查时允许自动
下载。先根据错误中的缺失路径，对照
[Provider 环境说明](PROVIDER_RUNTIME_ENVIRONMENTS.md)检查已安装依赖、批准的模型和目标机器上的冻结清单。

## 有内部 Stage 文件，是否代表 minimal 失效

`minimal` 控制公共返回路径范围，内部文件仍用于诊断和回放。锁定解析会另外公开合同所需的执行证据。调用方按 [输出模式](OUTPUT_MODES_ZH.md)和 Embedded 回执读取公开产物。

## 解析成功但结构不符合预期

依次检查：

1. `result/audit.json` 的 `validation`；
2. `result/document.json` 中的 Canonical 记录；
3. `full` 模式下的 `quality_gate`、`runtime_policy` 和 `production_manifest`；
4. 是否使用了预期的 Frozen route 和生产 Provider 配置。

不要通过调整阈值或 escalation 顺序临时绕过问题。保留该次 `run_dir`，用 reference-bound 回归
确认是输入差异、Provider 输出差异还是 Core 行为变化。

## 测试显示 SKIP

外部样本、旧工程路径或 Provider 环境缺失时，部分测试会跳过。`SKIP` 只说明前置条件没有提供，
不能作为真实 Provider、reference parity 或完整 PDF 解析通过的证据。
