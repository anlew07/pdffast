# PDFFast Embedded Execution Contract V1（设计草案）

> 状态：DESIGN DRAFT，尚未冻结、尚未作为生产合同发布。  
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

## 2. 当前已有能力（基线代码事实）

### 2.1 生产解析链路

`ParseService._parse_locked()` 已经：

1. 加载并验证 Production Profile。
2. 执行生产 Preflight。
3. 独占保留新的 run 目录。
4. 记录输入 PDF 的 SHA-256 和字节数。
5. 将已验证的 Profile、Provider 配置、Registry 和候选链快照交给 Core。

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

## 3. 当前缺口

1. `result/manifest.json` 目前没有统一的 Execution Contract Schema 标识。
2. 公开 Manifest 有输入 SHA 和结果路径，但没有对交付产物逐项提供 SHA-256、字节数和相对路径清单。
3. 公开 Manifest 没有明确引用 `production_execution_manifest.json`、`selected_prediction_index.json`、实际执行策略及任务级 attempts 证据。
4. `parser_provenance` 有 attempted/selected Provider 计数和 effective fingerprint，但当前没有把 Preflight 返回的各 Provider runtime identity 明确纳入 provenance；具体包版本、模型 revision/资产身份主要由 fingerprint 间接绑定。
5. `ParseResult.artifacts` 在 minimal 模式只公开最终结果文件路径，不直接公开全部关键执行证据路径。
6. 解析异常、Audit 失败、进程被强杀时，不保证存在最终结果 Manifest；这属于现有合同明确的失败边界，需要由 typed error、进程退出码和 JOB_ID 持久回执共同表达，不能伪造成功 Manifest。

## 4. 建议的合同形态

### 4.1 复用现有合同，不替代它们

新的外部合同命名为 `pdffast.execution.v1`，是 Embedded 结果交付层，不替代：

- Production Parser Identity V1
- Parser Provenance V1
- Deployment Control V1

建议继续以 `result/manifest.json` 作为每次成功/部分完成解析的权威结果入口，在现有字段上增加 Execution Contract 字段；不另造一套互相竞争的 Manifest。

### 4.2 建议的核心结构

以下为结构草图，字段细节和 Schema 仍待评审：

```json
{
  "schema_version": "pdffast.execution.v1",
  "run_id": "core-run-id",
  "input": {
    "algorithm": "sha256",
    "sha256": "64-char-lowercase-hex",
    "byte_size": 12345,
    "status": "COMPLETE"
  },
  "result": {
    "document": "result/document.json",
    "markdown": "result/document.md",
    "audit": "result/audit.json"
  },
  "execution": {
    "execution_status": "COMPLETED",
    "pdffast_commit": "40-char-commit",
    "source_sha256": "64-char-sha256",
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
    "audit_passed": true
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
  ]
}
```

约束：

- `run_id` 始终指 Core 解析执行身份。
- 路径使用相对于本次 run 目录的 POSIX 路径；不得包含 run 目录之外的路径、符号链接逃逸或任意绝对路径。
- 对 JudgeAI 实际接收的最终文档、Markdown、Audit，以及关键执行证据文件生成 SHA-256 和字节数。
- 任务级 `selected_predictions/*.json` 是 fallback/attempts 的细粒度证据，应纳入可验证清单，或以有明确定义的目录树摘要覆盖；不能只留下一个无法追溯的 SUCCESS。
- `result/manifest.json` 是根合同文件本身，不在自己的 artifacts 列表中计算自身摘要，避免循环摘要。消费者可以在读取后独立计算该文件的 SHA-256 并持久化。
- `provider_runtime` 应复用当次 Preflight 的实际 runtime identity（包版本、模型 revision/资产验证信息）；实际使用哪些 Provider 仍以 attempted/selected 计数为准。
- `policy_version` 从实际执行的 runtime escalation policy 读取，不由 JudgeAI 推断。
- `execution_evidence` 只引用现有执行证据，不复制或重写整个 fallback 历史。

### 4.3 状态语义

解析结果状态沿用现有来源，不把部分失败折叠成成功：

| 状态 | 含义 | JudgeAI 是否接收为成功解析 |
| --- | --- | --- |
| `COMPLETED` | 锁定解析完成，Provider 任务统计一致，Audit PASS，必要产物已写入 | 仍须由 JudgeAI 完成 SHA、Schema、身份和进程回执验证 |
| `COMPLETED_WITH_PIPELINE_FAILURES` | Pipeline 产生了显式任务失败/诊断产物 | 否 |
| `CONFIGURATION_FAILED` | 配置或 Profile 无效 | 否 |
| `PREFLIGHT_FAILED` | 生产运行时或身份预检未通过 | 否 |
| `EXECUTION_FAILED` | Core/Provider 执行异常 | 否 |
| `OUTPUT_VALIDATION_FAILED` | Audit 或输出校验失败 | 否 |
| 进程中断/强杀 | 可能没有最终 Manifest | 由 JOB_ID 回执和 OS returncode 判定，绝不推断为成功 |

`COMPLETED` 只代表 PDFFast 侧完成其门禁；不等于 OCR 内容已人工确认准确，也不替代 JudgeAI 自己的身份与产物验证。

## 5. 输入身份与产物身份

- PDFFast 记录解析开始时观察到的 PDF SHA-256 和字节数。
- 当前 `fingerprint_input()` 明确不是输入文件快照；调用方必须保证输入在整个解析期间不可变。
- JudgeAI 应在解析完成后重新计算原始 PDF SHA-256，与执行 Manifest 的输入 SHA 比较；不一致即拒收。
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

## 7. ParseResult 的兼容扩展方向

建议在现有 `ParseResult` 上增加只读的 `execution_contract` 访问入口，并在 minimal 输出模式下公开关键执行证据路径。

要求：

- 保留现有 `canonical`、`markdown`、`audit`、`artifacts`、`production_manifest`、`parser_provenance` 属性及旧 mapping 访问。
- 锁定生产模式提供 `pdffast.execution.v1`；非锁定默认模式不冒充生产合同。
- Embedded runner 从稳定对象/最终 Manifest 消费合同，不解析终端人类可读日志。
- 当前 JudgeAI 生产路径使用 JudgeAI 自己的 Embedded Runner；本任务不把 PDFFast 的 standalone `scripts/run_pipeline.py` 误当作 JudgeAI 唯一入口，也不为其新增不必要的 HTTP/CLI 适配层。

## 8. 实施顺序

1. 先补 Schema 与合同测试（成功、Native-only、发生回退、部分失败、产物篡改、输入变化、路径逃逸）。
2. 扩展 `parser_provenance`，显式携带当次 Provider runtime identity 和策略版本；保持现有统计校验。
3. 扩展最终 `result/manifest.json`，增加 Execution Contract、关键执行证据引用和产物摘要。
4. 扩展 `ParseResult`，保持现有 API 兼容。
5. 为失败和进程中断路径补充合同级测试；不得声称所有异常都能产生最终 Manifest。
6. 更新 Embedded 集成合同文档；不修改 HTTP。
7. 在目标 macOS 环境使用五份真实 PDF 回归，并由 JudgeAI 在后续集成阶段独立复核输入与产物摘要。

## 9. 验收门禁

- [ ] 生产路由、候选顺序和 Provider 执行策略没有变化。
- [ ] `pdffast.execution.v1` Schema 可验证。
- [ ] Native-only（0 Provider tasks）仍能生成合法合同。
- [ ] 实际 Provider、运行时身份、策略版本和 effective fingerprint 可追溯。
- [ ] fallback attempts、batch history、任务级结果均可定位并校验。
- [ ] `COMPLETED_WITH_PIPELINE_FAILURES` 不会被映射为 `COMPLETED`。
- [ ] 所有交付产物具有可验证 SHA-256、字节数和 run-relative 路径。
- [ ] 输入 PDF 身份可与调用方原始文件复核。
- [ ] run_id 与 JOB_ID 语义清晰且关联可持久化；同一 Job 恢复不会重复启动解析。
- [ ] 现有 V1 身份、Provenance、Deployment Control 合同及旧 ParseResult 访问保持兼容。
- [ ] 五份真实 PDF 在 macOS Embedded/Core 子进程环境完成回归。
- [ ] HTTP 未被纳入本阶段范围。

## 10. 当前审查结论

- A01 内部自主路由：已有实现，保持不动。
- A02 执行身份/恢复：现有 run_id + JOB_ID + reconcile 能力可复用；主要补充消费方关联和语义清晰度，不新增 execution_id。
- A03 Manifest：已有多层证据，但缺少统一外部结果入口、Provider runtime 可读身份和产物摘要清单。
- A04 HTTP：本阶段明确 DEFERRED，不作为验收项。

本文件是设计草案。完成文件级审查、用户确认和 Schema 评审前，不应据此批量修改解析核心。
