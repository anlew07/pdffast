# PDFFast Embedded Execution Contract V1

> Embedded V1 已发布到 `main`。本规范覆盖本地 Python 和 Embedded CLI。[JudgeAI 接入合同](../integration/JUDGEAI_EMBEDDED_EXECUTION_CONTRACT_V1.md)提供调用和验签操作，[真实 PDF 验收](../../B06-A5_REAL_PDF_ACCEPTANCE.md)记录发布前的实测证据。

## 1. 合同范围

Embedded V1 汇集输入身份、生产身份、Provider 执行证据和可验证的产物。调用方负责提供 PDF 与预期摘要、保存执行结果并完成验证。PDFFast 根据锁定 Profile、质量门禁和候选链决定如何解析。进程任务状态由 [Deployment Control V1](deployment_control_v1.md)管理。现有 HTTP 服务有独立的请求与响应结构。

## 2. 请求和执行入口

`PDFFastParser.parse_request(pdf_path, request)` 使用部署端配置的锁定 Production Profile。
调用方在请求外传入本地 `pdf_path`。输出根目录由部署端构造 Parser 时配置。
`ParseService` 校验请求后，在加载 Production Profile、执行 Preflight 和预留 run 目录之前计算 PDF 指纹。
输入不可用、为空或与预期 SHA-256 不一致时，版本化调用在该阶段失败。

请求的唯一结构由 [Request Schema](embedded_execution_request.v1.schema.json) 定义。

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

`run_id` 长度为 1 至 128 字符，首字符为 ASCII 字母、数字或下划线，后续可使用 ASCII 字母、数字、下划线、短横线和点。V1 的 `options` 为空对象。
Provider、Profile、质量阈值、回退链、路径和模型参数由部署端配置。
旧 `parse(pdf_path, run_id=...)` 继续支持原调用形式。

### 2.1 已有生产链路

版本化请求的摘要通过校验后，`ParseService._parse_locked()` 加载并验证 Production Profile，执行生产 Preflight，独占保留新的 run 目录，再将输入 SHA-256 和字节数及已验证的配置、Registry 和候选链快照交给 Core。旧入口保持原有处理次序。

`run_core_pipeline()` 已经完成 Native、Evidence、Quality、Fallback Planning、Capability Routing、Provider Execution、Canonical、Renderer 和 Audit。

本合同只消费这条链路的结果，不改变其路由决策。

### 2.2 已有执行证据

| 现有产物/对象 | 已有职责 |
| --- | --- |
| `result/manifest.json` | run_id、输入指纹、结果路径、parser_provenance |
| `production_execution_manifest.json` | Provider 执行汇总、batch_history、任务索引 |
| `selected_prediction_index.json` | 每个任务的选中结果和状态索引 |
| `selected_predictions/*.json` | 每个任务的 attempts、接受情况、升级触发原因、选中 Provider |
| `runtime_escalation_policy.json` | 实际执行的候选链和策略版本 |
| `parser_provenance` | 锁定 Profile 身份、实际 Provider 计数、任务结果计数、执行状态、Audit 和输出门禁 |
| `ParseResult` | 已暴露 canonical、markdown、audit、artifacts、production_manifest、parser_provenance |

### 2.3 已有身份与恢复能力

- Core 的 `run_id` 是一次解析执行的身份；锁定模式要求单段安全名称，并拒绝重复使用已保留的 run 目录。
- `deployment_recovery.prepare()` 生成独立的 32 位 `JOB_ID`，代表受管 OS 进程任务，不是 Core run_id。
- `deployment_control_v1.md` 已要求调用方持久化 `JOB_ID` 与 Core `run_id` 的对应关系。
- Worker/Manager 恢复时应使用原 `JOB_ID` 执行 `reconcile`，并由原任务继续协调。
- 用户主动重新解析时创建新的 Core `run_id` 和新的 `JOB_ID`。
- 当前恢复机制是进程任务恢复和回执协调，不是解析 Pipeline 的断点续跑。

**兼容性提醒：** deployment control V1 的 JSON 回执字段名 `run_id` 历史上承载的是 `JOB_ID`。它不能被解释为 Core 解析 `run_id`。JudgeAI 持久化字段应分别命名为 `job_id` 与 `core_run_id` 两个名字。

## 3. 结果入口与失败边界

`result/manifest.json` 承载 `execution_contract`，也保留旧有输入、结果和溯源字段。锁定模式下 `ParseResult.execution_contract` 暴露相同对象。合同记录实际运行时身份、锁定配置指纹和可独立校验的产物及执行证据。

Python 调用的执行失败由类型化异常表达，调用方可用 `to_contract()` 获取 [Error Schema](embedded_execution_error.v1.schema.json) 定义的响应。版本化 CLI 使用 `--expected-input-sha256`，同时传入 `--provider-profile` 与 `--run-id`，在 stdout 返回一份 JSON。stderr 和运行目录中的日志仅供受控诊断。

## 4. 结果合同

### 4.1 复用现有合同，不替代它们

新的外部合同命名为 `pdffast.execution.v1`，是 Embedded 结果交付层，不替代：

- Production Parser Identity V1
- Parser Provenance V1
- Deployment Control V1

继续以 `result/manifest.json` 作为每次成功/部分完成解析的权威结果入口，在现有字段上增加 `execution_contract` 字段；不另造一套互相竞争的 Manifest。Schema 位于 [`embedded_execution.v1.schema.json`](embedded_execution.v1.schema.json)。

### 4.2 核心结构

以下片段展示主要字段。完整约束见同目录 JSON Schema。版本化成功结果携带 `request`，其形状与 Request Schema 相同。离线 Schema 校验时按 Request Schema 的 `$id` 注册该文件，以解析结果 Schema 的 `$ref`。旧入口返回的结果省略 `request`。

```json
{
  "schema_version": "pdffast.execution.v1",
  "run_id": "core-run-id",
  "status": "SUCCESS",
  "input": {
    "algorithm": "sha256",
    "sha256": "64-char-lowercase-hex",
    "byte_size": 12345,
    "status": "COMPLETE"
  },
  "result": {
    "document": "result/document.json",
    "markdown": "result/document.md",
    "audit": "result/audit.json",
    "manifest": "result/manifest.json"
  },
  "execution": {
    "execution_status": "COMPLETED",
    "pdffast_commit": "40-char-commit",
    "source_sha256": "64-char-sha256",
    "source_dirty": false,
    "algorithm_sha256": {},
    "profile_name": "production-profile-name",
    "profile_sha256": "64-char-sha256",
    "providers_config_sha256": "64-char-sha256",
    "effective_config_fingerprint": "64-char-sha256",
    "policy_version": "existing-policy-version",
    "allowed_providers": [],
    "provider_runtime": {},
    "attempted_provider_counts": {},
    "selected_provider_counts": {},
    "escalated_count": 0,
    "terminal_preserve_count": 0,
    "pipeline_failure_count": 0,
    "preflight_status": "PASS",
    "audit_passed": true,
    "outputs_written": true
  },
  "execution_evidence": {
    "production_manifest": "09_8_production_fallback/production_execution_manifest.json",
    "selected_prediction_index": "09_8_production_fallback/selected_prediction_index.json",
    "runtime_policy": "09_6_3_runtime_policy/runtime_escalation_policy.json"
  },
  "artifacts": [
    {
      "name": "document",
      "path": "result/document.json",
      "media_type": "application/json",
      "byte_size": 12345,
      "sha256": "64-char-lowercase-hex"
    }
  ],
  "warnings": [],
  "risk_flags": [],
  "error": null
}
```

约束：

- `run_id` 始终指 Core 解析执行身份。
- 路径使用相对于本次 run 目录的 POSIX 路径；不得包含 run 目录之外的路径、符号链接逃逸或任意绝对路径。
- 对 JudgeAI 实际接收的最终文档、Markdown、Audit，以及关键执行证据文件生成 SHA-256 和字节数。
- 任务级 `selected_predictions/*.json` 是 fallback/attempts 的细粒度证据，应纳入可验证清单；每个 `selected_prediction` artifact 同时携带 `task_id`，JudgeAI 应按 `task_id` 与 `selected_prediction_index.items` 关联。
- 现有 `selected_prediction_index` 内部的 `selected_prediction` 字段是历史绝对路径。为保持旧执行产物兼容，PDFFast 本阶段不改写它；JudgeAI 不应直接信任/跟随该绝对路径，而应使用 Execution Contract 的 run-relative artifact 路径，并验证其 SHA-256、字节数和根目录边界。
- `result/manifest.json` 是根合同文件本身，不在自己的 artifacts 列表中计算自身摘要，避免循环摘要。消费者可以在读取后独立计算该文件的 SHA-256 并持久化。
- `provider_runtime` 应复用当次 Preflight 的实际 runtime identity（包版本、模型 revision/资产验证信息）；实际使用哪些 Provider 仍以 attempted/selected 计数为准。
- 当前 `ParseService` 调用生产 Preflight 时使用默认 `probe=False`：因此 `status=READY` 表示严格运行时身份/资产检查通过，`dependency_probe=NOT_RUN` 表示尚未调用 Provider 自身的 `preflight()`。实际执行阶段仍会执行 Provider preflight；消费者不得把 `READY` 或 `preflight_status=PASS` 解释为已完成 OCR 推理或已证明 Provider 可成功处理任务。
- `policy_version` 从实际执行的 runtime escalation policy 读取，不由 JudgeAI 推断。
- `source_dirty` 与 `algorithm_sha256` 复用现有 `code_identity`：前者显式说明 PDFFast checkout 是否存在受监控的未提交改动，后者保留 Native、Quality、Fallback Policy、Canonical、Renderer、Audit 等算法源码指纹。dirty 状态不在本阶段自动拒绝，但 JudgeAI 应保留该信息用于审计和复现判断。
- `execution_evidence` 只引用现有执行证据，不复制或重写整个 fallback 历史。

### 4.3 结果状态和信号

外层 `status` 采用 `SUCCESS` 或 `PARTIAL_SUCCESS`。锁定解析经过 Audit 并生成可用内容后，有终态保留时返回 `PARTIAL_SUCCESS`。内部 `execution.execution_status` 和各项计数继续记录实际任务完成情况。发布给 JudgeAI 前，独立验签还会校验 Schema、输入身份和真实产物摘要。

`warnings` 中的元素包含 `code`、`stage`、`message` 和可选 `details`。`risk_flags` 从当次警告代码生成。信号来源包括旧调用未提供期望摘要、当次预检未运行可选依赖探测、终态保留、任务失败和源码工作区有修改。结果响应的 `error` 固定为 `null`。

Provider 链耗尽且没有策略允许的终态保留时，现有 Canonical 门禁无法构建可审计结果，执行返回 `FAILED` 和 `PROVIDER_EXECUTION_FAILED`。只有占位符或空 Markdown 的执行也返回 `FAILED`。Provider 初始化错误包含 Provider、初始化状态、关联任务 ID 和异常类型。原始异常字符串、配置和本机绝对路径仅留在本地诊断。

| 状态 | 判断依据 | Embedded CLI 退出码 |
| --- | --- | --- |
| `SUCCESS` | 所有必要任务和产物门禁通过 | 0 |
| `PARTIAL_SUCCESS` | 已通过 Audit 且有可用文档，部分任务以终态保留结束 | 4 |
| `BLOCKED` | 请求、输入、生产预检或 run 预留失败 | 2 |
| `FAILED` | 解析异常、无可用结果、Audit 失败或发布失败 | 3 |
| `CANCELLED` | Core 观察到明确的协作取消请求 | 5 |
| `INTERRUPTED` | 父进程观察到异常退出且无法确认有效结果 | 由父进程根据退出信号与任务回执判断 |

## 5. 输入身份与产物身份

- PDFFast 记录解析开始时观察到的 PDF SHA-256 和字节数。
- 在构建最终 Execution Contract、发布 `result/manifest.json` 之前，PDFFast 会重新读取输入 PDF 并比较 SHA-256 与字节数；不一致或文件不可读时拒绝发布成功 Manifest。
- 这仍不是不可变文件快照：如果外部进程在解析期间修改文件、随后又恢复成原字节，首尾指纹无法证明每个 Stage 读取的是同一份字节。因此调用方仍必须保证输入在整个解析期间不可变。
- JudgeAI 仍应在解析完成后重新计算原始 PDF SHA-256，与执行 Manifest 的输入 SHA 比较；不一致即拒收。
- JudgeAI 对每个交付产物重新计算 SHA-256 和字节数，与 PDFFast Manifest 比较。
- JudgeAI 还应验证所有产物路径均位于该 `run_id` 的输出根目录内。
- 不能仅凭文件存在、HTTP/进程退出码为 0、或 deployment state 为 `COMPLETED` 就接受解析结果。

## 6. 执行身份与恢复约定

调用方持久化关联：

```text
review_task_id
  ├── core_run_id       # PDFFast ParseService.run_id
  └── job_id            # deployment_recovery.prepare() 返回的 JOB_ID
```

- 请求超时、JudgeAI Worker 重启：使用原 `job_id` 查询/协调，不重新启动 Core。
- Job 为 RUNNING：继续查询原 Job。
- Job 为 COMPLETED：先核对 `accepted_exit`、`cleanup_complete`，再读取并验证原 `core_run_id` 的 Manifest 和产物。
- Job 为 FAILED、CANCELLED、CANCEL_PENDING 或状态不确定：不得接收已有部分产物为成功；按 Deployment Control V1 的规则继续协调或失败处理。
- 用户主动重新解析：创建新的 `core_run_id` 和 `job_id`，保留旧运行证据。
- 不要求 PDFFast 根据 run_id 自动重放或从中间 Stage 恢复。

## 7. Python 对象与 CLI 的兼容性

`ParseResult` 继续提供 `canonical`、`markdown`、`audit`、`artifacts`、`production_manifest` 和 `parser_provenance`。锁定 Profile 交付结果时增加 `execution_contract`，`minimal` 也会公开相关证据路径。普通非锁定解析的 `execution_contract` 为 `None`。旧锁定入口 `parse()` 省略回执中的 `request`，版本化入口则回显该字段。

版本化 CLI 的 stdout 承载与根 Manifest 内嵌合同相同的结果回执，或符合错误 Schema 的失败回执。调用和部署验收步骤见 [JudgeAI Embedded 接入合同](../integration/JUDGEAI_EMBEDDED_EXECUTION_CONTRACT_V1.md)。

## 8. 合同验证

`scripts/verify_production_governance.py` 独立核对 Schema、根 Manifest、Provenance、Provider Manifest 和实际策略，重新计算产物 SHA-256 及字节数，并校验 run-relative 路径、任务 ID、尝试顺序和 batch history。完整交付要求输入和产物身份一致、Audit 通过、状态为 `SUCCESS`。

当前实现的合同、产物篡改、异常和受管恢复边界由本地测试覆盖。[B06-A5](../../B06-A5_REAL_PDF_ACCEPTANCE.md)记录五份文件的输入核验及一份代表样本的真实 Embedded 解析。部署时仍需对目标机器、锁定提交与业务适配器验收。
