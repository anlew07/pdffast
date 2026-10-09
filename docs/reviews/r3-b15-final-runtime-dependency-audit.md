# R3-B15 Final Runtime Dependency Audit

审计范围：当前 `PDFFastParser.parse()` 的 fresh production 调用；只读源码与既有测试，不以历史 Stage 文档推断运行行为。本报告中的“回读”指同次解析把 **PDFFast 刚写出的中间语义 artifact** 重新读入，才能计算下一步。读取原始 PDF、配置、Provider 自身输出不属于该定义。

## 结论与分类

**Fresh production 的 PDFFast 自有中间 JSON Runtime File Bus（F）= 0。** 运行链在各计算边界传递内存对象或 dict/list；同一批结果仍完整写入原有路径。下面的兼容文件入口仍可读 artifact，但 `parse()` 没有调用这些读取分支。静态审计未发现以已有 artifact 是否存在决定 fresh 算法走向的依赖。R3-B 对象驱动收敛满足冻结条件；本轮没有运行全量测试，不能把此前的绿色基线冒称为本轮执行结果。

分类：A `OBSERVABILITY_SIDECAR`（回归、诊断、审计输出）；B `PERSISTENCE_REPLAY_BOUNDARY`（持久化文件，可供离线复核/重放）；C `COMPATIBILITY_FILE_API`（旧文件入口）；D `CONFIG_POLICY`（运行配置与固定策略）；E `PROVIDER_NATIVE_IO`（Provider 的模型、输入、输出及自身引用）；F `RUNTIME_FILE_BUS`（PDFFast 自有中间文件作为 fresh 必经计算总线）。A/B/C 可同时适用于同一 artifact 的不同用途。B 只表示文件具备离线复核/重放价值，**公开 `parse()` 并未实现 resume/reuse**。

## 公开入口和完整运行图

`PDFFastParser.parse` 构造/转交 `ParserConfig` → `ParseService.parse` 装配 Provider 配置、`ProviderRegistry`、normalizer 与 `PipelineContext` → `run_core_pipeline`：

```text
PDF → Profiler(profile + snapshot observations)
    → Generic Section Discovery(section alignment)
    → Page Structure → Table Recovery → TextFlowResult
    → EvidenceReport → QualityReport → FallbackPlan → CapabilityPlan
    → frozen policy + route candidates → ProviderExecutionPlan
    → ProviderTask → RawProviderResult → normalized CanonicalPrediction
    → ProviderExecutionResult(selection + selected index)
    → DocumentUnit reconciliation + Stage10 Canonical dict
    → Renderer(markdown + render manifest)
    → Audit dict → ParseResult
```

`ParseService` 从项目或打包资源读取 `providers.json`；frozen policy 读取 route candidates。这两次读取属于 D。Profiler/Quality/Fallback 读取原始 PDF；Fallback 将任务页面/区域渲染成执行输入图像。Provider worker 可读取自己的输出文件，这些均不属于 F。

## 逐边界对象交接

“NO”表示 fresh 路径不回读该行的中间 artifact。`dict`/`list` 是当前真实数据形状，并不暗示已有专门类型。

| Boundary | Producer → consumer | Fresh transport | Artifact | Artifact role | Runtime reload? |
|---|---|---|---|---|---|
| Profiler → Section Discovery | `run_profiler` → `run_section_discovery` | `profile: dict`、`snapshot_pages: dict[int, dict]` | profile、snapshot JSONL | A/B/C | NO |
| Profiler → Page Structure | `run_profiler` → `run_page_structure` | profile、`snapshot_meta/pages` | profile、snapshot | A/B/C | NO |
| Section Discovery → Page Structure | `run_section_discovery` → `run_page_structure` | `section_alignment: dict` | `section_alignment.json` | A/B/C | NO |
| Page Structure → Table Recovery | `run_page_structure` → `run_table_recovery` | `page_structure: dict` | `page_structure.json` | A/B/C | NO |
| Profiler snapshot → Table Recovery | `run_profiler` → `run_table_recovery` | `snapshot_pages` | snapshot JSONL | A/B/C | NO |
| Native objects → TextFlow | Profiler/Page Structure → `create_text_flow_result` | `snapshot_meta/pages`、`page_structure` | snapshot、structure | A/B/C | NO |
| Table Recovery → TextFlow | `run_table_recovery` → `create_text_flow_result` | `table_result: dict` | `result.json` + Markdown | A/B/C | NO |
| Native/TextFlow → Evidence | Native producers/`TextFlowResult` → `create_evidence_report` | profile、snapshot、alignment、structure、table dicts；`TextFlowResult` | Stage 1–6 JSON/JSONL/Markdown | A/B/C | NO |
| Evidence → Quality | `create_evidence_report` → `evaluate_evidence_report` | `EvidenceReport.data` | Evidence JSON/Markdown | A/B/C | NO |
| Quality → Fallback | `evaluate_evidence_report` → `create_fallback_plan` | `QualityReport.data` | Quality JSON/Markdown、probe crops | A/B/C | NO |
| Fallback → Capability | `create_fallback_plan` → `create_capability_plan` | `FallbackPlan.data` | fallback manifest JSON/Markdown、task images | A/B/C; images are execution input | NO |
| Capability → frozen policy | `create_capability_plan` → `create_provider_execution_plan` | `CapabilityPlan.data` + route candidate config | provider plan JSON/Markdown；route config | plan A/B/C; config D | NO (config read: YES, D) |
| Policy → Executor | `create_provider_execution_plan` → `execute_provider_plan` | `ProviderExecutionPlan.data` | runtime policy JSON/Markdown | A/B/C | NO |
| Executor → Normalizer | `provider.execute` → `normalize_runtime_result` | `RawProviderResult` + task dict | `provider_raw/<task>.json`、`runtime_manifest.json` | A/B/C | NO; Provider raw refs may be E |
| Normalizer → Selection | `normalize_prediction` → executor evaluation | normalized prediction dict held in `states[*].attempts` | embedded in selected wrapper/manifest; no required standalone normalized file | A/B | NO |
| Selection → Stage10 | executor → `run_stage10` | `ProviderExecutionResult` (`manifest`, `selected_index`, `selected_predictions`) | production manifest、selected index、selected JSON files | A/B/C | NO |
| Section/TextFlow/Quality/Capability → Stage10 | runner → reconciliation + Canonical | alignment dict、`TextFlowResult.normalized_flow`、`QualityReport.data`、`CapabilityPlan.data` | same sidecars | A/B/C | NO |
| Canonical → Renderer | `build_document` → `build_rendered_document` | canonical dict | canonical `document.json` | A/B/C | NO |
| Runtime objects → Audit | runner → `audit` | normalized flow、Quality、canonical、render manifest dicts、Markdown string | `document.md`、render manifest、Audit JSON | A/B/C | NO |
| Audit/runtime → ParseResult | `run_stage10` → `ParseResult.from_pipeline` | canonical dict、Markdown string、audit dict、production manifest dict + path metadata | `result/{document.json,document.md,audit.json,manifest.json}` | A/B | NO |

Stage 6 另写 noise、reading order、paragraphs、cross-page paragraphs 和对应 Markdown；Evidence 直接使用 `TextFlowResult` 的字段。Table Recovery 另写 `result.md` 与 `logical_tables.md`。这些诊断文件均保留，无 fresh 回读。

## 静态文件读取审查及隐藏回退

对 `pipeline/native/quality/fallback/providers/canonical/render/audit` 检索了 `read_text`、`json.load`、`open(..., "r")`、JSONL 读入、文件存在检查和 selected/raw 文件扫描，并沿 `parse()` 实参逐个判定：

- Native 的 section、structure、table、TextFlow、Evidence 函数以 `is not None` 判断对象输入；fresh runner 全部提供，合法空 dict/list 不会误触文件分支。Profiler 对原始 PDF 的打开属于输入读取。
- Quality、Fallback、Capability 直接取上游 `.data`。Quality 原 PDF probe、Fallback PDF 渲染与 task image 写出是实际工作，不是中间 JSON 读取。
- Policy 读取 frozen route candidate 配置（D），不读取已写出的 provider plan。Executor 读取 execution plan 对象，没有重新载入 policy/plan JSON；任务空列表在对象路径保持空列表。
- `normalize_runtime_result` 写 raw task JSON 与 runtime manifest 后，把 `RawProviderResult` 转成内存 wire dict，连同对**即将/刚刚写出的字符串**计算的 SHA256 交给 `normalize_prediction`。`normalize_one` 只有 `result_data is None` 才读 raw task JSON；fresh 传入 dict。正常 fresh 的 raw task JSON 读取 0、runtime manifest 读取 0。RapidOCR 的 `provider_raw_refs` 可能被读取以取得空间文本，属于 Provider 原生证据（E），与 PDFFast 刚写的 raw task envelope 不同。
- `run_stage10` 中 `section_alignment is not None or a.section_alignment.is_file()` 在 fresh 实参下短路，DocumentUnit reconciliation 直接拿 `native_structure`、`native_flow`、`selected_index`、`selected_predictions`。它们即使为空容器，也不转到 `diagnose_recovered_heading_candidates` 的文件入口。
- Canonical builder 对 native flow、Quality、Capability/plan、selected index 使用 `is not None`；selected wrappers 使用 `is None` 才按目录读文件，空列表不触发。四种输入的 provenance hash 在 fresh 由内存 JSON 字节计算，不重新打开对应 artifact。因此 fresh Stage10 对 section alignment、normalized flow、Quality、provider plan、selected index 和 selected predictions 的读取均为 **0**。
- Renderer 直接消费 canonical dict。Audit 直接消费 TextFlow/Quality/Canonical/render manifest/Markdown；fresh Audit 对 normalized flow、Quality 的读取均为 **0**。Audit 与 Renderer 的单独 CLI/file API 仍可读文件。
- `ParseResult.from_pipeline` 从 `run_stage10` 返回 dict 构造 `canonical`、`markdown`、`audit`、`production_manifest`，只保存 artifact 路径；没有从 result 文件重新加载。`result` 目录的文件存在与否不驱动下一算法。

唯一表面上以中间 artifact 存在性为条件的 `run_stage10` alignment 分支，在正式对象参数下不会检查该文件。Native 结构函数的 snapshot 存在性检查只在 `snapshot_pages is None` 的 file API 分支。selected 文件缺失检查也只在 `selected_predictions is None` 的 file API 分支。未发现 fresh 的 artifact-existence 控制依赖。

## 其余 I/O 的归属

| 类别 | 仍会读取什么 | 理由 / 边界 |
|---|---|---|
| D CONFIG_POLICY | `providers.json`、frozen route candidates；Registry 的模型/manifest/required artifact 校验 | 外部配置与严格 preflight；不是本次解析生成的 JSON |
| E PROVIDER_NATIVE_IO | 原始 PDF/任务图像、模型文件；MinerU/Marker/Docling 等 worker 输出的 Markdown/JSON/HTML/图像；RapidOCR `provider_raw_refs` | Provider 计算及其自身证据交付；可能按文件协议返回内容 |
| C COMPATIBILITY_FILE_API | Native/表格/TextFlow/Evidence file 入口，Quality/Fallback/Capability/Policy/Executor file wrapper，raw-file normalizer，Stage10/DocumentUnit/Renderer/Audit file/CLI 入口 | 独立 regression、benchmark、脚本与历史调用可使用；公开 fresh parse 传对象 |
| A/B OBSERVABILITY/PERSISTENCE | 上表所有 stage sidecar、selected files、Canonical、Markdown、render manifest、Audit、公开 result 文件、日志 | 回归、benchmark、debug、人工核验、审计和离线复核；非 fresh 内存交接的前提 |
| F RUNTIME_FILE_BUS | 无 | 当前审计的 fresh `parse()` 链未发现 PDFFast 自有中间 JSON 写后必读 |

`providers/workers.py` 对 Provider 返回的 Markdown 路径执行 `read_text` 是 E；Registry 检查模型或 artifact existence 是 D/E。日志追加写入和写出结果文件是输出，不是下一阶段的读入。旧 `scripts/run_pipeline.py` 的 artifact 入口不表示公开 `parse()` 已支持 resume。

## Runner 职责、对象寿命与 mutation

`runner.py` 仍负责顺序编排、对象生命周期、Artifact 写入、配置路径转交、Provider 执行、Canonical 与 Audit handoff，并保留 `run_stage10` 的兼容文件分支。它没有在 fresh 路径中承担“加载本次中间 artifact 后继续计算”的职责；本轮不拆分 runner。

Profiler 创建 profile 与 snapshot dict；section、structure、table dict 依次创建并被 Native 下游使用。`snapshot_meta/pages` 和 `page_structure` 在 Evidence 构造后显式 `del`。`TextFlowResult` 供 Evidence、Stage10 与 Audit；`EvidenceReport` 在 Quality 后无下游保留；`QualityReport` 供 Fallback、Stage10、Audit；`FallbackPlan` 供 Capability；`CapabilityPlan` 供 Policy 与 Stage10；`ProviderExecutionPlan` 供 Executor。每个 task 的 `RawProviderResult` 在执行/标准化局部作用域；normalized prediction 保留在 executor attempts 中，选中 wrapper/index 汇入 `ProviderExecutionResult` 并供 Stage10 使用。Canonical dict 供 Renderer、Audit、ParseResult；render manifest/Markdown 供 Audit/ParseResult；Audit dict 进入 ParseResult。大对象随局部引用与返回值释放；当前未看到跨 parse 的全局累积容器。选中预测及尝试在单次执行内按任务保留，这是有界于本次任务数的设计，不能宣称常量内存。

R3-B 的下游只读约束在本次审查的交接处仍可见：reconciliation 建新结构，`with_document_units` 对 canonical 做 `deepcopy`；Canonical 建索引/记录，Audit 建自己的计数与列表。搜索到的 `.pop`、`.update`、原地 `.sort` 分别用于 reconciliation 新建局部映射/集合/排序列表；Profiler 的 `snapshot_meta.update` 是明确的生产端 out-parameter 填充。未发现对已交给下游共享的上游报告做破坏性修改；此判断限于所审查的边界，不等于对每个深层 helper 证明纯函数性。

## 冻结判定与验证口径

1. PDFFast 自有中间 artifact 的 fresh 写后读：**0**；F = **0**。
2. Provider 原生 I/O 单独归类 E；配置/策略读取归类 D。
3. 兼容文件 API 与 artifact writer 保留，Stage 1–10 以及公开 result 输出没有因本轮删除。
4. 既有对象 handoff 回归基线：full **311 passed、20 skipped、0 failed**；reference-bound **331 passed、0 failed**。这是用户提供并经 R3-B14 记录的冻结基线，**本轮未重跑 pytest**。
5. 本轮只新增本报告并运行静态搜索、`git diff --check`；不修改生产代码。

**判定：可以冻结 R3-B Object-Driven Convergence。已知 blocker：无。** 结论限于所审计的 fresh production 路径；第三方 Provider 输出、配置读取与离线文件入口继续存在。
