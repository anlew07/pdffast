# R3-B10 Post-Native Runtime Dependency Re-Audit

范围：当前 `PDFFastParser.parse()` 正式生产调用链的静态源码审计。本文不把独立命令、benchmark 的文件接口当作正式 `parse()` 的必经路径；也不把原始 PDF、Provider 的外部产物与 PDFFast 写后重读的 JSON 混为一谈。结论基于当前工作区源码，未重新运行解析或完整测试。

## 1. 完整运行链与对象状态

`PDFFastParser.parse` 构造/转交 `ParserConfig` → `ParseService.parse` 装配 `ProviderRegistry`、provider 配置与 `normalize_runtime_result` → `run_core_pipeline`：Profiler → Section Discovery → Page Structure → Table Recovery → `TextFlowResult` → `EvidenceReport` → `QualityReport` → `FallbackPlan` → `CapabilityPlan` → `ProviderExecutionPlan` → `ProviderExecutionResult` → `run_stage10`（DocumentUnit reconciliation、Canonical、Renderer、Audit）→ `ParseResult.from_pipeline`。

依据：`pdffast/parser.py`、`pdffast/application/parse_service.py`、`pdffast/pipeline/runner.py`、`pdffast/result.py`。runner 在进入 Canonical 前仍持有 `profile`、`table_result`、`text_flow_result`、`evidence_report`、`quality_report`、`fallback_plan`、`capability_plan`、`execution_plan`、`production`；`snapshot_meta`、`snapshot_pages`、`section_alignment`、`page_structure` 在 Evidence 写出后被删除。这不影响已产生的 Native 输出，但 Stage 10 目前仅接收 `context`，没有接收这些现存对象。

## 2. Native → Evidence：完成对象传递

Profiler 同时填充 `profile` 与 `snapshot_meta/snapshot_pages`；后续 Section Discovery、Page Structure、Table Recovery、TextFlow 的正式调用均显式传递已有内存数据。`create_evidence_report` 同时收到 `profile`、snapshot、alignment、structure、table 和 `TextFlowResult`，因此其文件兼容回退分支不会在正式调用中使用。各阶段仍写旧 artifact，路径还用于 provenance。**Native → Evidence object-driven = COMPLETE**；此处不存在为了继续计算而重新打开刚写出的 Stage 1–6 JSON。依据：`pdffast/pipeline/runner.py`、`pdffast/quality/evidence.py:create_evidence_report`。

## 3–6. Evidence、Quality、Fallback、Capability

| 边界 | 正式调用 | 文件角色 |
|---|---|---|
| Evidence → Quality | `evaluate_evidence_report(evidence_report, …)` 使用 `EvidenceReport.data` | Evidence JSON/Markdown 是 sidecar；`manifest_path` 提供 provenance。Quality 可读取原 PDF 做 probe，属原始输入。 |
| Quality → Fallback | `create_fallback_plan(quality_report=quality_report, …)` 使用 `QualityReport.data` | Quality JSON/Markdown 是 sidecar；`quality_gate_path` 用于引用。Fallback 会从原 PDF 渲染 Provider 输入图像，这是执行资源，不是 Quality JSON 数据总线。 |
| Fallback → Capability | `create_capability_plan(fallback_plan=…, …)` 使用 `FallbackPlan.data` | fallback manifest 是 sidecar/兼容输入；路径记入 plan provenance。 |
| Capability → execution policy | `create_provider_execution_plan(capability_plan, context.route_candidates)` 使用 `CapabilityPlan.data` | `route_candidates` 是冻结配置/策略文件，非本次 parse 的中间文件。 |

证据：`pdffast/quality/gate.py:evaluate_evidence_report`、`pdffast/fallback/planner.py:create_fallback_plan`、`pdffast/fallback/router.py:create_capability_plan`、`pdffast/fallback/policy.py:create_provider_execution_plan`。对应的 `create_quality_report`、`run_fallback_planning`、`run_capability_routing`、`run_runtime_policy` 等旧文件入口仍可读 artifact，但 runner 没调用它们。

## 7. Capability → Provider Execution

`execute_provider_plan(execution_plan=execution_plan, …)` 直接使用 `ProviderExecutionPlan.data`，验证 provider closure，并按 frozen chain 创建、预检、初始化、执行和关闭 Provider。正式执行不重读 `provider_plan.json` 或 `runtime_escalation_policy.json`。`execute_providers=False` 在当前 `run_core_pipeline` 会抛异常；公开 `ParseService` 固定传 `True`。因此现有正式入口没有 `resume/reuseExisting` 模式。独立 benchmark、policy replay、文件兼容 API 与生产调用须分开看。依据：`pdffast/pipeline/runner.py`、`pdffast/fallback/executor.py`、`scripts/run_pipeline.py`。

## 8. Provider raw result → Normalizer

`Provider.execute` 返回内存 `RawProviderResult(provider, task_id, status, payload, markdown, elapsed_seconds, warnings)`；Executor 直接把对象交给 `normalize_runtime_result`。但该适配器先把已持有的 raw payload 写入 `provider_raw/<task>.json`，并写 `provider_raw/runtime_manifest.json`，随后调用旧 `normalize_prediction`；`normalize_one` 用 `load_json(result_path)` 重新读任务结果。故此处**仍有 PDFFast 自身的 RUNTIME_FILE_BUS**，不能笼统称为端到端对象传递。归一化过程中个别 provider 的 `provider_raw_refs`、Markdown、HTML 等外部产物还可能被读取，属于 Provider 产物/兼容证据边界，需要单独保留。归一化函数最终返回内存 canonical prediction dict，没有要求调用方扫描目录。依据：`pdffast/providers/base.py`、`pdffast/providers/runtime_normalization.py`、`pdffast/providers/normalization.py:normalize_one,_rapidocr_spatial_items`。

## 9. Normalizer → Selection

Executor 将每次归一化的 dict 存入 `state[task_id]["attempts"]`，按状态、所需 text 与 structure channel 判断接受或升级；成功时保存 `selected_canonical`。这段选择计算直接用对象。结束后它构造 selected wrapper（任务身份、provider、terminal/failure、attempts、`selected_canonical`，以及兼容别名 `canonical_prediction`），写 `selected_predictions/<task>.json` 和 `selected_prediction_index.json`，同时在 `ProviderExecutionResult` 返回 `manifest`、`selected_index`、`selected_predictions` 三项内存数据。production manifest 也写盘。依据：`pdffast/fallback/executor.py`。

## 10. Selection → Canonical；额外 DocumentUnit 消费

`run_stage10(context)` 没有接收 `ProviderExecutionResult`。Canonical builder 加载 selected index，再按 `task_id` 从 selected directory 打开每个 wrapper。DocumentUnit reconciliation 也调用 `diagnose_recovered_heading_candidates`，重读 normalized flow、selected index 与同一批 wrapper；还重读 native section alignment。它们是**同次 parse 写后重读**，同时这些产物也提供可核验的持久化和历史独立调用输入。`ProviderExecutionResult.selected_predictions` 已包含新鲜运行所需的 wrapper，但当前没有直接接入 Stage 10。依据：`pdffast/pipeline/runner.py:run_stage10`、`pdffast/canonical/_stage10_builder.py:build_document`、`pdffast/canonical/document_units.py:resolve_document_units_from_artifacts`、`pdffast/structure_reconciliation/heading_candidates.py:diagnose_recovered_heading_candidates`。

## 11. Normalized flow → Canonical

Builder 从 `normalized_text_flow.json` 读取 `page_count`、`source_file`、`page_index`、`sections`、`records` 等；`TextFlowResult.normalized_flow` 已是写出该 JSON 的同一 dict，并无仅由序列化才产生的语义字段。Canonical 以 records 为 Native provenance backbone，并以 sections/page index 组织页。DocumentUnit reconciliation 与 Audit 也重读此 JSON。JSON 的 path/SHA256 被写入 Canonical `inputs`，因此未来直接传对象时仍须保持这条 artifact hash/provenance 契约。依据：`pdffast/native/text_flow.py:TextFlowResult,write_text_flow_result`、`pdffast/canonical/_stage10_builder.py:build_document`。

## 12. Quality → Canonical

Builder 重读 `quality_gate.json`，使用 `pages[*].decision/route/non_text_assessment.regions` 与 `summary` 衍生 page/region fallback 判定、region 到 Native record 的 provenance 映射，以及页信息；`QualityReport.data` 已存在于 runner 内存。Audit 也再次加载该 JSON。Quality 文件的 path/SHA256 同样写入 Canonical `inputs`。依据：`pdffast/canonical/_stage10_builder.py:build_qg_region_index,build_document`、`pdffast/pipeline/runner.py:run_stage10`。

## 13. Provider plan → Canonical

Builder 重读的是 **CapabilityPlan 的 `provider_plan.json`**，不是 runtime policy JSON。实际使用 `source_file/page_count/stage/artifact_role` 做契约校验，`tasks` 的 `task_id/task_type/page_number/source_id/source_bbox/input_image/capability_route/stage8_decision/stage8_route/stage8_gate_state/route_hints` 做任务闭合验证与 fallback overlay/provenance；选中 provider、尝试次数、terminal outcome 等则来自 selected wrapper。`CapabilityPlan.data` 是这份文件的直接内存来源；`ProviderExecutionPlan` 则是 frozen chain 执行语义，不能替代 CapabilityPlan 的全部 Stage 10 metadata。依据：`pdffast/canonical/_stage10_builder.py:validate_inputs,build_document`、`pdffast/fallback/router.py:create_capability_plan`。

## 14. Selected prediction 的实际契约

Builder 校验 wrapper 与 plan/index 的 task ID、task type、页码、source ID、capability route 一致；拒绝 `ground_truth_used` 或 `pipeline_failure`；terminal REGION 必须无 selected prediction，非 terminal 必须有非空文本。它读取 wrapper 的 `selected_provider`、`terminal_fallback_applied/action`、`attempts` 数量及升级状态、`policy_class/provider_chain`、`runtime_outcome/source_content_preserved/capability_gaps` 和 `selected_canonical`。`compact_canonical` 保留 prediction 的 `provider`、`text`、`spatial_text`、`tables`、`formulas`、`reading_blocks`、`relations`、`diagnostics`、`warnings`、`exception`、`normalization_policy`、状态、版本和耗时。部分 wrapper 字段在当前 Executor 的新产物中可缺省，builder 使用 `get`/默认值；并非每个列出的字段都必定有值。选中 prediction 的来源身份和 reference path 也进入 Canonical provenance。依据：`pdffast/canonical/_stage10_builder.py:compact_canonical,validate_inputs,build_document`。

## 15. Canonical Builder 的职责

`canonical/builder.py` 是文件路径入口，并附加 `document_units`。`_stage10_builder.py` 同时承担文件加载/哈希、跨文件闭合校验、Native record/Quality region 索引、fallback 与 Native 记录的保守合并、page/region/inline overlay、provenance、summary、Canonical schema 组装；不是单纯 serializer。`document_units.py` 又从 Native/selected 文件重建 recovered heading 与 coverage，再附加独立的 DocumentUnit 维度。因此迁移输入方式时必须保持校验、merge 和 hash/provenance 行为。依据：上述三个模块。

## 16. Canonical → Renderer → Audit → ParseResult

Renderer 通过 `build_rendered_document(canonical)` 直接接收内存 dict，返回 `markdown, manifest`；**此边界已经 object-driven**，不会重读刚写的 Canonical JSON。Audit 直接收到 canonical、render manifest、markdown 对象，但 runner 对 Native flow 和 Quality 两个输入调用 `_load(path)`；所以 **Audit 只部分 object-driven**。最后 `ParseResult.from_pipeline` 从 `final` 的 canonical、markdown、structure_audit 及 production manifest 对象构造，仅保存 artifact 路径，不重读结果文件。独立 Renderer/Audit CLI 有文件输入接口，不等于正式生产依赖。依据：`pdffast/pipeline/runner.py:run_stage10`、`pdffast/render/llm_ready.py`、`pdffast/audit/structure_boundary.py`、`pdffast/result.py`。

## 17–20. 剩余文件分类与 reuseExisting

同一文件可同时承担 A 与 C；分类描述的是**本次 parse 的使用方式**及其保留价值。

| 文件/输入 | 类别 | 理由 |
|---|---|---|
| Stage 1–5、Evidence、Quality、Fallback、provider plan、runtime policy 的中间 JSON/Markdown | B；其中 Quality、provider plan、section alignment 又为 A | 前半段对象链不会读它们；Stage 10 会重读 Quality、provider plan、section alignment。文档、回归与独立文件接口仍需要这些文件。 |
| `06_stage6/normalized_text_flow.json` | A+B/C | Canonical、DocumentUnit reconciliation、Audit 同次重读；兼容、回归、provenance hash 亦使用。 |
| `08_stage8/quality_gate.json` | A+B/C | Canonical、Audit 同次重读；Quality→Fallback 不重读。 |
| `09_2_provider_plan/provider_plan.json` | A+B/C | Canonical 同次重读；policy/Executor 不重读。 |
| `03_stage3/section_alignment.json` | A+B/C | Stage 10 的 DocumentUnit reconciliation 同次重读；Native→Evidence 已对象化。 |
| `09_8_production_fallback/selected_prediction_index.json` 与 `selected_predictions/*.json` | A+C | Canonical 和 reconciliation 同次重读；也是可核验的 Provider 选择结果与历史回放输入，不能删除。 |
| `09_8_production_fallback/provider_raw/<task>.json` | A+C | runtime Normalizer 写后读 raw JSON；旧归一化合同、原始证据/诊断继续使用。Provider 自身输出的 Markdown/JSON/图像路径可能另需读取。 |
| `09_8_production_fallback/provider_raw/runtime_manifest.json` | B/C | 适配器写出文件，但同时将内存 manifest 传给 normalizer；当前正常路径不重读该 manifest 文件。其路径用于 raw ref 解析与来源记录。 |
| `09_8_production_fallback/production_execution_manifest.json` | B/C | 返回值同时保留内存 manifest；后续 Stage 10 不重读该文件。 |
| `10_1_canonical/*.json`、`10_2_llm_ready/*`、Audit 与 `result/*`、日志/诊断图像 | B/C | 同次 Renderer/Audit/ParseResult 不从这些最终输出恢复对象；供用户、审计、回归使用。 |
| 原 PDF 与渲染出的 Provider 输入图像 | 原始输入/执行资源 | 必须打开以观察 PDF 或供 Provider 执行；不属于语义对象写后重读。 |
| `configs/providers.json`、`configs/frozen/stage9_route_candidates_prod_v001.json` 或包内资源 | D | 前者由 ParseService 加载为配置，后者由 frozen policy 加载；均非本次 parse 产生。 |

源码未发现公开 `reuseExisting` 参数、状态判断或生产 resume 分支。`scripts/run_pipeline.py` 明确 `--from-artifacts` 尚未启用；现有 `run_stage10(context)` 和旧文件 API 能消费已持久化 artifact，历史 `_run_replay.py` 属一次性验收脚本，**不能据此声称正式 parse 已支持 reuseExisting**。目前 fresh-run 是对象链到 Provider selection，再经 selected 文件重读进入 Stage 10；未来若支持 reuse，可采用 fresh object→object、resume artifact→校验/水合 object→object 双入口，并继续写现有文件以维持审计和回放能力。此处是建议模型，不是当前实现。

## 21–24. 唯一建议的下一刀

**优先迁移 `ProviderExecutionResult.selected_predictions/selected_index → Stage 10` 这一条边界。** fresh production 已持有经过 selection 的完整 wrapper/index，然而 Canonical 和 DocumentUnit reconciliation 都立即从 selected 文件重建它们；这是明确且重复的同次运行文件总线。保持 `selected_predictions/*.json`、index、manifest 的写出、task 闭合验证、文件 hash/provenance 与独立文件入口；只让正式 runner 将既有对象传给两个下游消费者，旧 artifact 路径在 replay/compatibility 入口水合成相同输入。parity 可比较 Canonical、DocumentUnit、Audit、selected 文件逐项等价，不需改 Provider 执行或 merge 算法。

主要风险：`diagnose_recovered_heading_candidates` 目前为每个 wrapper 添加 `prediction_reference` 文件路径；Canonical `selected_prediction_file` 与 `inputs` 中的 SHA256 也依赖已经落盘的文件。对象直传仍须保留并按原时序计算这些引用与哈希。Terminal unresolved、pipeline failure、task ID 闭合和 provider provenance 校验不能因跳过文件读取而弱化。Normalizer 的 raw 写后读也是独立的 A 类问题，但它牵涉多 Provider 的离线归一化合同和外部 raw refs；本轮建议先收口已有完整执行结果对象的下游交接。
