# R4-B Semantic Artifact Layout Contract

## 范围和原有结构

本轮只隔离“语义产物名称”与“历史物理路径”。`ArtifactPaths` 原有 18 个 frozen dataclass 字段是平铺的 `Path`；`result_dir`、`result_document`、`result_markdown`、`result_audit`、`result_manifest`、`pipeline_log` 是派生属性。`for_run()` 把编号目录字面量集中映射到这些字段。`as_dict()` 被 `ParseResult(full)` 使用，因此这些旧字段及返回键保留。

原有顶层 `run_core_pipeline` / `run_stage10` 通过这些平铺字段获取路径，Provider executor 自己从 execution output dir 拼 `provider_raw`、`selected_predictions`、index 与 manifest；Native/Evidence/Canonical 等兼容 file API 仍接收旧路径参数。本轮没有移动文件、增加物理目录、创建 symlink、复制新副本、修改配置/策略或变更 JSON/Markdown/Audit。`02_stage2` 已无 fresh writer，也没有新增语义职责。

## 新增语义 API

`ArtifactPaths` 新增只读、frozen 的五组视图：`result`、`native`、`observability`、`diagnostics`、`providers`。视图**由现有字段派生**，不是新的存储来源，也不是 dataclass 字段；旧属性继续是兼容 alias。`ArtifactPaths.as_dict()` 的键和值不变，`ParseResult` 源码与 public mapping 未修改。`providers.raw_result(task_id)`、`selected_prediction(task_id)` 由旧 execution dir 派生路径；`normalized_prediction(task_id)` 明确返回包含 normalized attempts 的 **selected wrapper 路径**，当前没有独立的 normalized JSON 文件。

| Semantic Name | Legacy Physical Path（`<run>/` 下） | Category | Compatibility Alias | Future Migration Candidate |
|---|---|---|---|---|
| `result.document_json` | `result/document.json` | RESULT | `result_document` | 稳定保留 |
| `result.document_md` | `result/document.md` | RESULT | `result_markdown` | 稳定保留 |
| `result.audit_json` | `result/audit.json` | RESULT/AUDIT | `result_audit` | 稳定保留 |
| `result.manifest_json` | `result/manifest.json` | RESULT | `result_manifest` | 稳定保留 |
| `result.canonical_snapshot` | `10_1_canonical/canonical_document.json` | RESULT/REPLAY | `canonical_document` | 仅未来审查历史副本 |
| `result.rendered_snapshot` | `10_2_llm_ready/llm_ready.md` | RESULT/REPLAY | `llm_ready` | 仅未来审查历史副本 |
| `native.profile` | `01_stage1/page_profile.json` | DIAGNOSTICS/REPLAY | `profile` | 可后续语义化目录 |
| `native.snapshot` | `01_stage1/page_snapshot.jsonl` | DIAGNOSTICS/REPLAY | `snapshot` | 可后续语义化目录 |
| `native.sections` | `03_stage3/section_alignment.json` | DIAGNOSTICS/REPLAY | `section_alignment` | 已是 Generic Section Discovery；可后续改路径名 |
| `native.page_structure` | `04_stage4/page_structure.json` | DIAGNOSTICS/REPLAY | `page_structure` | 可后续语义化目录 |
| `native.tables` | `05_stage5/result.json` | DIAGNOSTICS/REPLAY | `table_result` | 可后续语义化目录 |
| `native.text_flow` | `06_stage6/normalized_text_flow.json` | DIAGNOSTICS/REPLAY | `normalized_flow` | 可后续语义化目录 |
| `observability.evidence` | `07_stage7/evidence_manifest.json` | OBSERVABILITY | `evidence_manifest` | 可后续语义化目录 |
| `observability.quality` | `08_stage8/quality_gate.json` | OBSERVABILITY | `quality_gate` | 可后续语义化目录 |
| `observability.fallback_plan` | `09_1_fallback_units/fallback_execution_manifest.json` | OBSERVABILITY/REPLAY | `fallback_manifest` | 可后续语义化目录 |
| `observability.capability_plan` | `09_2_provider_plan/provider_plan.json` | OBSERVABILITY/REPLAY | `provider_plan` | 可后续语义化目录 |
| `observability.execution_plan` | `09_6_3_runtime_policy/runtime_escalation_policy.json` | OBSERVABILITY/REPLAY | `runtime_policy` | 可后续语义化目录 |
| `observability.production_manifest` / `providers.production_manifest` | `09_8_production_fallback/production_execution_manifest.json` | OBSERVABILITY/PROVIDERS | `production_manifest` | 可后续语义化目录 |
| `observability.render_manifest` | `10_2_llm_ready/render_manifest.json` | OBSERVABILITY | `render_manifest` | 可后续语义化目录 |
| `observability.structure_audit` | `10_2_1_structure_audit/structure_boundary_audit.json` | OBSERVABILITY | `structure_audit` | 可后续审查历史副本 |
| `providers.selected_index` | `09_8_production_fallback/selected_prediction_index.json` | PROVIDERS/REPLAY | `selected_prediction_index` | 可后续语义化目录 |
| `providers.selected_dir` | `09_8_production_fallback/selected_predictions/` | PROVIDERS/REPLAY | `selected_predictions_dir` | 可后续语义化目录 |
| `providers.raw_dir` | `09_8_production_fallback/provider_raw/` | PROVIDERS/REPLAY | 旧 `production_manifest.parent / "provider_raw"` 拼接 | 可后续语义化目录 |
| `providers.raw_manifest` | `09_8_production_fallback/provider_raw/runtime_manifest.json` | PROVIDERS/REPLAY | 旧 execution-dir 拼接 | 可后续语义化目录 |
| `providers.raw_result(task_id)` | `09_8_production_fallback/provider_raw/<task_id>.json` | PROVIDERS/REPLAY | 旧 execution-dir 拼接 | 可后续语义化目录 |
| `providers.selected_prediction(task_id)` | `09_8_production_fallback/selected_predictions/<task_id>.json` | PROVIDERS/REPLAY | 旧 selected-dir 拼接 | 可后续语义化目录 |
| `providers.normalized_prediction(task_id)` | 同一个 selected wrapper，normalized attempts 嵌在其中 | PROVIDERS/REPLAY | 无独立旧文件 | **不得**误认为新文件 |
| `diagnostics.text_flow_dir` | `06_stage6/` | DIAGNOSTICS | `normalized_flow.parent` | 可后续语义化目录 |
| `diagnostics.probe_crops_dir` | `08_stage8/probe_crops/` | DIAGNOSTICS | `quality_gate.parent / "probe_crops"` | 可后续语义化目录 |
| `diagnostics.fallback_inputs_dir` | `09_1_fallback_units/inputs/` | DIAGNOSTICS/PROVIDERS | `fallback_manifest.parent / "inputs"` | 可后续语义化目录 |
| `diagnostics.pipeline_log` | `diagnostics/logs/pipeline.log` | DIAGNOSTICS | `pipeline_log` | 保留路径 |

`result.dir` 是已有 `result_dir` 的视图；`providers.execution_dir` 是已有 `production_manifest.parent`。未把动态 Provider 文件变成 `ArtifactPaths` dataclass 字段，因此 `full` 模式的旧键集合不会扩大。

## 已迁移与暂留调用方

正式顶层 `pipeline/runner.py` 的 Native、Evidence/Quality/Fallback/Policy、Provider 执行目录、DocumentUnit/Canonical、Renderer、Audit、result/manifest 写入和失败日志交接改用语义分组。所有写入和 JSON 内记录的 `str(Path)` 仍指向原路径。`ParseResult.from_pipeline`、底层 Native/Quality/Provider 算法、旧 file API/CLI、历史测试 fixture 和文档保持原接口；Provider executor 内部仍在收到的旧 execution dir 下拼原文件名。内部函数名 `run_stage10`、`stage5_path`/`stage6_dir`、`_stage10_*` 文件名及 JSON 的 `stage`、`stage8_decision`、source refs、task id、frozen route candidate 文件名均未迁移。它们若需更名，涉及独立的兼容或 schema 审查，不属于本轮路径语义层。

## 验证与边界

- TDD：新增 path identity 测试最初因缺少语义属性失败（3 failed），新增 runner semantic-only proxy 测试最初因平铺访问失败（2 failed）；实现后相关测试通过。
- case_002：用真实 PDF 执行完整 Native→Evidence→Quality→Fallback→Capability→Policy→Stage10→Renderer→Audit；Provider execution 使用历史选中预测回放，**未启动模型**。在同一 run 路径、同一输入下比较前后，均为 **41 个相对文件路径**；新增 **0**、删除 **0**、字节变化 **0**。`result/manifest.json`、Canonical、Markdown、Audit 在字节比较范围内。此回放不验证真实 Provider 模型执行或其额外原生输出目录；相关路径由 identity 测试和既有 Provider 测试覆盖。
- `ParseResult` 未改；`as_dict()` 旧字段集合不变；`minimal/diagnostic/full` 原行为不变。
- 本轮不改任何实际目录、文件名、JSON path value、manifest path、Canonical schema、Markdown 内容、审计内容、Provider 选择或 frozen policy。
- 本轮完整测试：full **316 passed、20 skipped、0 failed**；reference-bound **336 passed、0 failed**。相对冻结基线（311/20、331）各增加 5 个通过项，skip 未变化。执行时使用已有环境的 `uv run --no-sync` 和 `/private/tmp` 下的 uv cache；没有启动重型 Provider。
