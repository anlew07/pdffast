# PDFFast 解析来源合同 V1

锁定 Core 解析在 `result/manifest.json` 追加 `parser_provenance` 对象，Python 中通过 `ParseResult.parser_provenance` 访问。同一个对象可用 [JSON Schema](parser_provenance.v1.schema.json) 验证。旧 manifest 字段、`production_manifest` 与旧 mapping 访问信息保持兼容。默认模式 Python 属性为 `None`，旧 manifest 无 V1 对象。

## 字段与约束

| 字段 | 类型和语义 |
| --- | --- |
| `schema_version` | 字符串 `"1.0"` |
| `profile_locked`、`profile_name`、`profile_sha256`、`providers_config_sha256`、`effective_config_fingerprint`、`allowed_providers`、`capability_routes`、`pdffast_commit`、`code_identity` | 使用当次实际锁定快照，字段类型见[身份合同](production_parser_identity_v1.md) |
| `planned_task_count` | 非负整数，运行时 execution plan 唯一 ID 数 |
| `attempted_provider_counts` | Provider 名称到正整数的对象。每次进入任务级 Provider 执行计一次，包括实际调用抛错并形成失败记录的情况。候选未调用、初始化和预检均无调用计数 |
| `selected_provider_counts` | Provider 名称到正整数的对象，等于真实 accepted prediction 的归属 |
| `accepted_task_count`、`terminal_preserve_count`、`pipeline_failure_count` | 非负整数，三类互斥且总和等于规划任务数 |
| `provider_execution_required` | 布尔值，由规划任务数是否大于零确定 |
| `execution_status` | `COMPLETED` 或 `COMPLETED_WITH_PIPELINE_FAILURES` |
| `preflight_status`、`audit_passed`、`outputs_written` | 最终对象中的值分别为 `PASS`、`true`、`true` |

执行器记录的 attempts 与派发批次、原序候选、每任务 wrapper、选中索引及 `production_execution_manifest.json` 汇总交叉校验。每个任务的已执行候选必须构成其 Profile 链的前缀，每个 accepted task 有且只有一个选中结果。计数与计划不一致、存在重复或缺失任务、实际结果身份对不上时，Core 执行失败。合法终止保留可存在于 `COMPLETED` 中。Stage 8 Native 完整时，两类计数对象都为 `{}`，各任务统计为 0，`provider_execution_required=false`，Native、Canonical、Renderer、Audit 仍完成真实执行。

## 最终发布与异常

锁定运行需要新的单段 `run_id` 对应一个不存在的目录。Core 以独占方式创建该目录，并在父目录保留锁定运行标记供默认模式拒绝写入。完成 Provider 清理、来源校验、结果写入、Audit 和最终取消检查后，原子发布最终 manifest。中间产物可以在失败时保留用于诊断。旧运行目录必须继续作为旧证据保存。JudgeAI 使用每次调度的新 run ID。

- `CONFIGURATION_FAILED` 通过 `ConfigurationError.status` 或预检状态返回。
- `PREFLIGHT_FAILED` 通过 `ProductionPreflightError.status` 或预检状态返回。
- `EXECUTION_FAILED` 通过 `ParseExecutionError.status` 返回，包括 Provider 初始化、清理和来源校验错误。取消或进程异常也视为失败。
- `OUTPUT_VALIDATION_FAILED` 通过 `OutputValidationError.status` 返回，例如 Audit 失败。
- `COMPLETED_WITH_PIPELINE_FAILURES` 表示解析生成了带显式失败计数的诊断产物。JudgeAI 拒绝接收为成功。
- `COMPLETED` 只证明 Core 已通过自身生命周期和输出校验。父进程负责验证实际 OS returncode，包括文件已存在后发生的 abort。

异常状态通过 API/CLI 或父进程观测传播。失败路径不保证有最终 manifest。对于 SIGKILL 或 native abort，Python 清理逻辑可能未运行。阶段 9 的 manifest 是内部执行证据，Stage 10 或父进程仍可能失败。

## JudgeAI 接受顺序

1. 锁定部署使用的解释器、源码身份、Profile 路径、Profile SHA、Provider 配置 SHA、有效指纹、Schema 版本。
2. 调度前对相同解释器、相同解析参数运行预检并校验 pin。生产名单和路线从预检合同读取。
3. 调用 Core 子进程，显式传入 Profile，使用唯一 run ID。等待 OS 退出，首先拒绝 `returncode != 0`。
4. 读取本次最终 manifest，核对 run ID 和 `input.sha256`。核对 Markdown、Canonical、Audit 均为本次运行的合法产物，且 Audit 通过。
5. 校验 provenance Schema、两份配置 SHA、有效指纹、`code_identity`、允许名单、完整路线与预检一致。要求 `profile_locked=true`、`COMPLETED`、失败数为零、Audit 和 outputs 均为真。
6. 核对尝试与选中 Provider 均属于允许名单，选中总数等于 accepted 数，三类任务结果等于计划数。零任务按 Native-only 接受。将 provenance 和 PDF SHA 与产物一起持久化。
7. 缓存键至少包含 PDF SHA-256、`effective_config_fingerprint`、Schema 版本。读取缓存时重新校验证据。将历史未锁定路由及无可信 provenance 的缓存隔离。

## 完整 JSON 示例

以下对象来自两页合成 Native-only PDF 的真实 Core 运行。哈希标识本地未提交候选与当次运行环境。正式部署应重新生成 pin。

```json
{
  "schema_version": "1.0",
  "profile_locked": true,
  "profile_name": "pdffast-v3-indra-rapidocr-mineru-candidate",
  "profile_sha256": "12446eefdfdc92dafc861c3c0fb8f76eb342b48b6e7659e40110927886d40971",
  "providers_config_sha256": "99c895dfef4016424621e8d614e27cb215b02ac78be114ce62de0e38a8e13dc3",
  "effective_config_fingerprint": "068d2bd00d78d18d422ad99f6820a7c7e48d72ac1de207c3294bd990a65480ed",
  "allowed_providers": [
    "indra_local",
    "rapidocr_ch_light",
    "mineru_local"
  ],
  "capability_routes": {
    "INLINE_CONTEXT_PARSE": [
      "indra_local",
      "mineru_local",
      "rapidocr_ch_light"
    ],
    "PAGE_DOCUMENT_LAYOUT_PARSE": [
      "mineru_local"
    ],
    "PAGE_DOCUMENT_OCR": [
      "indra_local",
      "rapidocr_ch_light",
      "mineru_local"
    ],
    "REGION_MULTIMODAL_PARSE": [
      "indra_local",
      "rapidocr_ch_light",
      "mineru_local"
    ]
  },
  "pdffast_commit": "63eeff3721b9b3de2acdc4de7df75bc9e61477f6",
  "code_identity": {
    "pdffast_commit": "63eeff3721b9b3de2acdc4de7df75bc9e61477f6",
    "source_dirty": true,
    "source_sha256": "130faa9911d9abe71717ed51ad13c76e82cc6920068d269b85174d735ed4f72e",
    "algorithm_sha256": {
      "native": "cacb5c66a7db59a527229a2409d1038a816bfc08e72302466242e733060a7cab",
      "evidence": "ee48dda40bc4a75ec0f03d4d15b06b0dafa9e486dd0461d260a6b4010f0e17a0",
      "quality": "e84d4f35d6fcb18509dd7dd51304da6ec1f191b20dd9f0f212a7799962ed0fb2",
      "fallback_policy": "8a3aa375913780209902ddfa0494fde09d8ab83983f6b6a9666aee394c6625aa",
      "canonical": "bfedc980e92ec2db6d401e0bbf9c051fe203592ecc9dc8fd038c9e5fc4b67385",
      "renderer": "658017e3d481ee48d859d54f0a5473b150b29359472fe6f91923ea9e67cc4fcc",
      "audit": "e4b7f12e820593e07a9bb6ec660683435281bce855d16d66ee945b4ca8a9d608",
      "structure_reconciliation": "99c2adb291a28100b72cd48bce8b2d621817d9b8db079abea8ce9c24b18e42ee"
    }
  },
  "planned_task_count": 0,
  "attempted_provider_counts": {},
  "selected_provider_counts": {},
  "accepted_task_count": 0,
  "terminal_preserve_count": 0,
  "pipeline_failure_count": 0,
  "provider_execution_required": false,
  "execution_status": "COMPLETED",
  "preflight_status": "PASS",
  "audit_passed": true,
  "outputs_written": true
}
```

