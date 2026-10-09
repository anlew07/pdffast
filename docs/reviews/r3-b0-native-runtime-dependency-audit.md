# R3-B0 Current Native Runtime Dependency Audit

日期：2026-09-29。范围：当前 `refactor/v3` 工作树的正式 `PDFFastParser.parse()` 路径。**本轮只审计，没有修改生产代码、解析算法、Artifact schema 或 outputs 命名。** 下文的“运行依赖”指同一次 parse 刚写出的文件必须再被读取，才能完成正式调用；保留文件本身不等于运行依赖。

冻结验收基线（由任务提供，本轮未重跑）：完整测试 **277 passed、15 skipped、0 failed**；reference-bound **292 passed、0 failed**。下一轮代码修改仍须以两套测试 0 failed 和真实样本 parity 验证。

## 1. 正式调用链

```text
PDFFastParser.parse
  → ParseService.parse → ParserConfig / ProviderRegistry / PipelineContext
  → run_core_pipeline
      → Profiler → Generic Section Discovery → Page Structure
      → Table Recovery → Text Flow → EvidenceReport → QualityReport
      → FallbackPlan → CapabilityPlan → ProviderExecutionPlan
      → ProviderExecutionResult
      → run_stage10
          → DocumentUnit reconciliation → Canonical Builder
          → Renderer → Structure Audit
  → ParseResult
```

证据：`pdffast/parser.py:15-39`、`pdffast/application/parse_service.py:19-85`、`pdffast/pipeline/runner.py:39-185`、`pdffast/result.py:15-55`。`ParseService` 读取 `configs/providers.json`（或包内资源）并组装依赖；`PipelineContext` 提供 PDF、运行参数、冻结路由配置和 Artifact 路径。`run_core_pipeline` 的现行实现从 PDF 执行至 Stage10；文件顶部“starts at Stage 10”的历史说明不符合该函数实现。公开入口始终传 `execute_providers=True`；`False` 分支在当前 runner 中抛异常，不是正式的 resume 流程。

## 2. Native 输入、输出与真实消费关系

| 职责 | 本次正式输入 | 计算产物 / 写出 | 后续如何消费 |
|---|---|---|---|
| Profiler / 原生观察 | 原 PDF 路径、`table_mode` | 单次 `pdfplumber.open` 的 page loop；逐页 `evidence` 包含原生文字、chars、words、图像、线/矩形/曲线、table candidates 和几何；同时计算 page profile。写 `page_snapshot.jsonl`（meta+pages）、`page_profile.json`；返回 profile `dict`。 | runner 丢弃返回值；Sections、Structure、Tables、TextFlow、Evidence 重读 snapshot，Sections、Structure、Evidence 重读 profile。`pdffast/native/profiler.py:1673-1940,1947-2165,2184-2335,2585-2615`。 |
| Generic Section Discovery | profile JSON 的 `source_file/page_count`、snapshot JSONL 的逐页原生证据 | `discover_sections(...)` 从内存 `snapshot_pages` 推导观察到的 headings、sections、page ownership、`unresolved_regions`，返回 `dict`；wrapper 写历史 `section_alignment.json`。 | runner 丢弃返回值；Structure 和 Evidence 重新读取该 JSON；Stage10 DocumentUnit reconciliation 也读它。`pdffast/native/sections.py:362-431`。没有模板定义参与。 |
| Page Structure | profile JSON、section alignment JSON、snapshot JSONL | `build_document_structure(...)` 组合 page profile、section/page ownership 与 raw geometry/text，产生页面块、边界、表格候选、验证等 `dict`；wrapper 写 `page_structure.json` 并返回。 | runner 丢弃返回值；Tables、TextFlow、Evidence 重读该 JSON。`pdffast/native/structure.py:3922-4115,5980-6005`。 |
| Table Recovery | page structure JSON、snapshot JSONL | 内部 `build_document(structure, snapshot_pages)` 已是内存计算；wrapper 写 `result.json`、`result.md`、`logical_tables.md` 并返回 `dict`。 | runner 丢弃返回值；TextFlow 和 Evidence 重读 `result.json`。Markdown 不被正式后续读取。`pdffast/native/tables.py:4468-4500,4798-4855`。 |
| Text Flow | snapshot JSONL、page structure JSON、table result JSON | `create_text_flow_result(...)` 一次计算 noise、reading order、paragraphs、cross-page paragraphs、normalized flow，返回 `TextFlowResult`；writer 写五份 JSON 及 Markdown 视图。 | **Evidence 直接接收 `TextFlowResult`**，不读这四份 Stage6 中间 JSON；但 Stage10 重读 `normalized_text_flow.json`。`pdffast/native/text_flow.py:113-119,21013-21138`。 |
| Evidence accounting | profile JSON、snapshot JSONL、section alignment JSON、page structure JSON、table result JSON，及 `TextFlowResult` | `EvidenceReport(data)`；writer 写 Evidence JSON/Markdown。 | Quality 直接接收 `EvidenceReport`，Evidence JSON 路径只用于输出的 `input` provenance。`pdffast/quality/evidence.py:48-51,1928-2010`、`pdffast/quality/gate.py:1734-1778`。 |

这不是线性 Stage 链。Evidence 是 Native 观察、章节、结构、表格和最终文本流的汇合点；即使 Stage6→Evidence 已对象化，前面五类文件仍是它的正式输入。Sections 的 `pages/sections/unresolved_regions` 经 Structure、Evidence 和 normalized flow 延续；Stage10 还直接读取 section alignment 做 DocumentUnit 调和。`TextFlowResult.cross_page_paragraphs` 是计算和 Artifact 的一部分，但 Evidence 的 object API 当前直接选用 `noise/reading_order/paragraphs/normalized_flow` 四项；cross-page 信息已参与 normalized flow 的生成。

## 3. 本次 parse 的 Runtime File Bus

下表只列实际参与正式路径的重读，不把仅记在 `inputs` 中的路径字符串算作重读。路径均由 `pdffast/pipeline/artifacts.py:55-101` 固定，文件名中的 Stage 编号暂时保留。

| 同次写出的文件 | 正式消费者 / 读取点 | 判定 |
|---|---|---|
| `01_stage1/page_profile.json` | Sections `sections.py:422`；Structure `structure.py:3932`；Evidence `evidence.py:1945` | **RUNTIME_FILE_BUS** |
| `01_stage1/page_snapshot.jsonl` | Sections `sections.py:364`；Structure `structure.py:3948`；Tables `tables.py:4806`；TextFlow `text_flow.py:21020`；Evidence `evidence.py:1946` | **RUNTIME_FILE_BUS**；同一原生观察被多次反序列化 |
| `03_stage3/section_alignment.json` | Structure `structure.py:3936`；Evidence `evidence.py:1947`；Stage10 `canonical/document_units.py:31` | **RUNTIME_FILE_BUS** |
| `04_stage4/page_structure.json` | Tables `tables.py:4805`；TextFlow `text_flow.py:21021`；Evidence `evidence.py:1948` | **RUNTIME_FILE_BUS** |
| `05_stage5/result.json` | TextFlow `text_flow.py:21022`；Evidence `evidence.py:1949` | **RUNTIME_FILE_BUS** |
| `06_stage6/normalized_text_flow.json` | Stage10 DocumentUnit reconciliation `canonical/document_units.py:32` 和 `heading_candidates.py:220`；Canonical `canonical/_stage10_builder.py:343`；runner 为 Audit `_load` `pipeline/runner.py:79` | **RUNTIME_FILE_BUS**；Stage6→Evidence 本身已经不是 |
| `08_stage8/quality_gate.json` | Canonical `canonical/_stage10_builder.py:344`；runner 为 Audit `_load` `pipeline/runner.py:80` | **RUNTIME_FILE_BUS**，尽管 Quality→Fallback 已对象化 |
| `09_2_provider_plan/provider_plan.json` | Canonical `canonical/_stage10_builder.py:345` | **RUNTIME_FILE_BUS**，尽管 Capability→Policy→Executor 已对象化 |
| `09_8_production_fallback/selected_prediction_index.json` 和 `selected_predictions/*.json` | Stage10 DocumentUnit reconciliation `heading_candidates.py:221-227`；Canonical `canonical/_stage10_builder.py:346-354` | **RUNTIME_FILE_BUS**；Executor 已返回等价的内存 `selected_index/selected_predictions`，runner 未传给 Stage10 |
| `09_8_production_fallback/provider_raw/*.json` 中的原始结果 / `runtime_manifest.json` | `runtime_normalization.py:58-68` 先写原始 result；`providers/normalization.py:2704-2710` 通过 `normalize_one` 重读 result。Normalizer 还可能按 raw refs 读取辅助文件，计算 source hash。 | **Provider 内部局部文件输入**；不在本轮 Native 迁移范围，不能误标为纯 sidecar |

Stage10 的 DocumentUnit 路径有 `section_alignment.is_file()` 条件检查（`runner.py:45`）：缺文件时它跳过该增强；正常正式 parse 已写该文件，所以当前正式 DocumentUnit 计算仍经文件输入。这里的 `heading_candidates.py` 函数说明称“development review”，但实际已被 `run_stage10` 调用，应按当前调用事实分类。Canonical Builder 现行签名只有五个 Artifact `Path` 加两个内存 DocumentUnit 参数，尚无同等的 Native/Quality/selection 对象 API（`pdffast/canonical/builder.py:25-47`）。

## 4. 旁路、持久化与配置分类

| 分类 | 当前例子 | 保留理由 / 现状 |
|---|---|---|
| Observability sidecar | Stage5 `result.md`、`logical_tables.md`；Stage6 `noise_candidates.json`、`reading_order.json`、`paragraphs.json`、`cross_page_paragraphs.json` 及各 Markdown/readable views；Evidence JSON/Markdown；Fallback manifest；runtime policy JSON/Markdown；production execution manifest；Canonical/Markdown/render/audit/result copies 和 pipeline log | 在**当前正式对象路径**中，下一步不靠它们的内容做决定。仍用于 regression、benchmark、人工检查、provenance、公开输出。注意 Stage6 `normalized_text_flow.json`、Quality JSON、provider plan JSON、selected prediction 文件不在此类。 |
| Persistence / compatibility input | `run_text_flow`、`run_evidence_manifest`、`create_quality_report`、`run_fallback_planning`、`run_capability_routing`、`run_runtime_policy`、`execute_fallback` 等旧 file API；独立 `run_stage10` 可消费已有 Artifact。 | 应保留测试/脚本/迁移读取能力。当前公开 `parse()` 和 CLI **没有启用** `reuseExisting`/resume 模式；`scripts/run_pipeline.py:24-29` 明说 `--from-artifacts` 未启用。不能以一个未来模式解释正式运行的重复读取。 |
| Policy / configuration | `configs/providers.json` 或包内同名资源；`configs/frozen/stage9_route_candidates_prod_v001.json`（`policy.py:713`）；ParserConfig/Context 的 DPI、table mode、output mode。 | 是解析前确定的配置/冻结路由数据，天然可从磁盘或包资源读取；不属于“本次运行刚写出的中间文件”。 |

“旁路”只是对本次正式消费者关系的分类，不主张删除。某些输出路径字符串进入后续 Artifact 的 `input(s)`/source provenance；这些字符串有追溯意义，但不会因此成为对文件内容的读取。Normalizer 的临时 raw result 是例外，已在上表单列。最终 `ParseResult` 返回 canonical、Markdown、audit 内存值及结果路径；结果文件是公开交付物，不是下一步解析输入。

## 5. 已存在的对象边界与缺口

`TextFlowResult → EvidenceReport → QualityReport → FallbackPlan → CapabilityPlan → ProviderExecutionPlan → ProviderExecutionResult` 在正式 runner 中确实逐个以 Python 值传递（`runner.py:153-171`）。`ProviderExecutionResult` 内含 manifest、selected index、selected predictions；目前只有 manifest 继续以对象传给 `ParseResult`，后两者到了 Stage10 又退回文件读取。Stage10 的 reconciliation 内部已使用 `RecoveredHeadingReport`、提案/预览、`DocumentUnit`、admission 与 `DocumentCoverageResult` 等对象；这些对象进入 Canonical 的 `document_units/admissions` 参数，但 reconciliation 的**入口**仍为 Artifact 路径。

Native 前半段缺少跨模块持有同一次原生扫描的语义边界。可以考虑内部“原生观察”值：文档 source/page count、snapshot meta、逐页 raw observation、page profiles；它表示**对 PDF 一次原生扫描得到的事实**，不等同于最终章节/表格/flow。另一个可能的长期边界才是“原生分析结果”：已发现的 section、page structure、recovered tables、final flow，以及 unresolved/provenance；它表示 Native 解析最终知道什么。名称和字段需要未来阶段结合内存开销与消费者契约决定，本轮**不创建**对象，也不把 `Stage1Result/Stage4Result/Stage5Result` 升格为领域模型。现有 `discover_sections`、`tables.build_document` 已以 dict 输入计算；难点主要在 wrapper/runner 的数据所有权。

## 6. PDF 读取次数与 runner 职责

Profiler 对原 PDF 进行一次 `pdfplumber.open`、一次 page loop，同时得出 profile 并逐页写 snapshot（`profiler.py:2206-2317`）。Sections、Structure、Tables、TextFlow、Evidence **没有再次做 Native PDF 扫描**，但各自重新加载 snapshot JSONL。Quality 在 uncertain 页面做 PDF 文件名/页数校验及视觉 probe（`gate.py:1328-1374`）；Fallback 为 Provider task 渲染输入图像时打开 PDF（`planner.py:204`）。后两者属于不同的视觉检查/渲染职责，不能算重复 Native 文本扫描，也不能因本次对象化删除。

runner 目前同时承担：顺序编排；从 `ArtifactPaths` 组装每个旧 file API 的路径；调用多处 writer；将最终 Stage10 输入从文件重载；把冻结路由配置传给 policy 实现；选择/准备 Canonical、Renderer、Audit 输入并写最终结果/日志。具体 Provider chain 和 Quality/Fallback 决策仍在对应模块，不在 runner 内实现。下一轮应缩小一条边界的文件依赖，无需同时拆 runner。

## 7. 推荐的独立迁移顺序

每步保留原有 writer 和 file compatibility wrapper，先证明对象路径不依赖被替换的 JSON，再比对对应 JSON/Markdown、Native records/顺序、Evidence accounting；每步独立提交并运行完整与 reference-bound 测试。

1. **R3-B1 Table Recovery → TextFlow/Evidence。** 接住 `run_table_recovery` 已返回的 document `dict`，给现有 TextFlow/Evidence 核心 API 增加可选的内存输入；正式 runner 使用它，旧文件入口保留。移除 `result.json` 在两个消费者处的正式重读，不改表格算法或 schema。用缺失/改名 `result.json` 的对象路径测试及新旧 Stage5、Stage6、Evidence Artifact parity 验证。Stage5 结果已在内存，省去重新持有完整 snapshot 的首轮内存风险。
2. **R3-B2 observed sections → Structure/Evidence。** 接住 `run_section_discovery` 返回的 dict，仅为这两个消费者建立对象输入；保留 section alignment JSON、原有校验和 Stage10 读取。验证 headings、section IDs、unresolved、page ownership 及 Artifact parity。
3. **R3-B3 page structure → Tables/TextFlow/Evidence。** 接住 `run_page_structure` 返回的 dict，复用已有 `tables.build_document(structure, snapshot_pages)`；不重写结构/表格算法。验证结构 JSON、table JSON、TextFlow 和 Evidence parity。
4. **R3-B4 Profiler 原生观察 → Sections/Structure/Tables/TextFlow/Evidence。** 让一次 PDF page loop 的原生观察在正式调用内有明确所有者，同时继续写原样 JSONL/profile；去掉这些消费者对同次 snapshot/profile 的必要重读。此步需要先测最大真实样本的峰值内存，避免简单累积整份 raw snapshot 造成不受控开销，并保持完整性验证。
5. **后续独立的 Stage10 边界。** 将 `TextFlowResult`、`QualityReport`、`CapabilityPlan`、`ProviderExecutionResult` 与已存在 DocumentUnit 对象直传 Canonical/reconciliation/Audit；继续写全部历史 Artifact。这个步骤不属于本次 Native 前半段的首刀，不能混入 R3-B1。

**下一次代码修改唯一推荐：R3-B1，只打通 Table Recovery 返回值到 TextFlow 和 Evidence 的内存输入。** 它直接消除两个重复读取点，且输入 dict 已由现行算法返回，回归面最小。`Profiler → snapshot` 是更大的高收益边界，但涉及全量原生 page evidence 的生命周期/内存；应在前几步确定消费者契约后单独实施。
