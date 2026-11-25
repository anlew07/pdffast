# PDFFast Embedded Execution Contract V1

> 已完成本地 Embedded 合同验收。[真实 PDF 验收](../../B06-A5_REAL_PDF_ACCEPTANCE.md) 和 [JudgeAI 交付文档](../integration/JUDGEAI_EMBEDDED_EXECUTION_CONTRACT_V1.md) 提供实测与接入说明。
> 基线：`feat/pdffast-production-governance-v1@0d497ebe3ca416d865a3cd16994d444bdde1e00f`。
> 范围：仅覆盖 JudgeAI 当前计划使用的本地 Embedded/Core 子进程集成；HTTP 暂缓。

## 1. 目标与非目标

目标是把 PDFFast 已有的生产身份、Provider 执行证据、解析结果和部署进程回执，组合成一个稳定、可验证的 Embedded 执行合同，供 JudgeAI 消费。

本任务不重新设计 PDFFast 解析路由，不重写已有内部合同，也不要求 JudgeAI 指定 Provider。

明确不做：

- 不修改 Native Analysis、Quality Gate、Fallback Planning、Capability Routing、Provider Registry、Frozen Runtime Policy、Provider Execution 或 Canonical Merge 的策略语义。
- 不改变 Indra、RapidOCR、MinerU 的候选顺序、能力路由或回退规则。
- 不实现 HTTP 合同、HTTP 查询、HTTP 幂等或 HTTP 与 Embedded 一致性验收。
- 不新增重复的 `execution_id`。
- 不实现从 Stage 中间状态断点续解析。
- 不把部署进程成功等同于解析成功。

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
- Worker/Manager 恢复时应使用原 `JOB_ID` 执行 `reconcile`，而不是再次启动同一 Core 解析。
- 用户主动重新解析时创建新的 Core `run_id` 和新的 `JOB_ID`。
- 当前恢复机制是进程任务恢复和回执协调，不是解析 Pipeline 的断点续跑。

**兼容性提醒：** deployment control V1 的 JSON 回执字段名 `run_id` 历史上承载的是 `JOB_ID`。它不能被解释为 Core 解析 `run_id`。本阶段不擅自改写已存在的 V1 回执字段；新合同和 JudgeAI 持久化字段必须明确使用 `job_id` 与 `core_run_id` 两个名字。

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

## 7. ParseResult 的兼容扩展（本分支已初步实现）

本分支已在现有 `ParseResult` 上增加 `execution_contract` 访问入口，并在锁定生产模式的 minimal 输出中公开关键执行证据路径。

要求：

- 保留现有 `canonical`、`markdown`、`audit`、`artifacts`、`production_manifest`、`parser_provenance` 属性及旧 mapping 访问。
- 锁定生产模式提供 `pdffast.execution.v1`；非锁定默认模式不冒充生产合同。
- Embedded runner 从稳定对象/最终 Manifest 消费合同，不解析终端人类可读日志。
- 当前 JudgeAI 生产路径使用 JudgeAI 自己的 Embedded Runner；本任务不把 PDFFast 的 standalone `scripts/run_pipeline.py` 误当作 JudgeAI 唯一入口，该脚本同时提供可独立调用的 Embedded JSON 模式。

## 8. 实施顺序与当前进度

1. **Schema 与合同测试：已初步完成。** 新增 `embedded_execution.v1.schema.json` 和 `test_embedded_execution_contract.py`，覆盖 Native-only、部分失败、无效身份、路径逃逸、产物摘要和输入 PDF 首尾指纹不一致。
2. **Execution Contract Builder：已初步完成。** 新增 `pdffast/application/execution_contract.py`，复用当次 Preflight runtime identity、Production Profile 身份、实际策略版本、执行统计和既有 Manifest。
3. **最终 Manifest：已初步接入。** 锁定生产模式在 `result/manifest.json` 中增加 `execution_contract`；不改变非锁定默认模式。
4. **ParseResult：已初步接入。** 增加 `execution_contract` 属性和关键执行证据路径；保留既有 mapping 键。
5. **独立生产验收：已初步接入。** `scripts/verify_production_governance.py` 会独立核对 Execution Contract 与 root Manifest / Provenance / Provider Manifest / runtime policy 的身份和统计一致性，逐项重算 artifact SHA-256 与字节数，并验证 run-relative 路径、selected prediction task_id、任务 attempts 与冻结 Provider chain、batch_history 的一致性；文件篡改和路径逃逸会导致验收 FAIL。
6. **失败与中断边界：已接通。** CLI 与 Python 异常使用相同错误 Schema，父进程负责协调无回执的中断。
7. **HTTP：不实施。** 本阶段不修改 HTTP Adapter。
8. **真实样本：A5 已验收。** 五份 PDF 通过输入与请求校验，代表 PDF 完成一次真实 Embedded 执行和逐产物验签。

## 9. 验收门禁

- [ ] 生产路由、候选顺序和 Provider 执行策略没有变化。
- [ ] `pdffast.execution.v1` Schema 可验证。
- [ ] Native-only（0 Provider tasks）仍能生成合法合同。
- [ ] 实际 Provider、运行时身份、策略版本和 effective fingerprint 可追溯。
- [ ] fallback attempts、batch history、任务级结果均可定位并校验。
- [ ] `COMPLETED_WITH_PIPELINE_FAILURES` 不会被映射为 `COMPLETED`。
- [ ] 所有交付产物具有可验证 SHA-256、字节数和 run-relative 路径。
- [ ] 生产验收脚本独立重算产物摘要，并拒绝篡改、路径逃逸或任务证据不一致。
- [ ] 输入 PDF 身份可与调用方原始文件复核。
- [ ] run_id 与 JOB_ID 语义清晰且关联可持久化；同一 Job 恢复不会重复启动解析。
- [ ] 现有 V1 身份、Provenance、Deployment Control 合同及旧 ParseResult 访问保持兼容。
- [ ] 五份真实 PDF 核对输入身份，代表样本在 macOS 完成真实 Embedded/Core 端到端回归。
- [ ] HTTP 未被纳入本阶段范围。

## 10. 当前审查结论

- A01 内部自主路由：已有实现，保持不动。
- A02 执行身份/恢复：现有 run_id + JOB_ID + reconcile 能力可复用；主要补充消费方关联和语义清晰度，不新增 execution_id。
- A03 Manifest：已有多层证据，但缺少统一外部结果入口、Provider runtime 可读身份和产物摘要清单。
- A04 HTTP：本阶段明确 DEFERRED，不作为验收项。

PDFFast 侧已通过本地合同和真实 PDF 交付验收。JudgeAI 端按交付合同进行 Embedded 联调。
