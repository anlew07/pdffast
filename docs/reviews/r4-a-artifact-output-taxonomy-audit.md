# R4-A Artifact / Stage Output Taxonomy Audit

范围：当前 `PDFFastParser.parse()` → `ParseService` → `run_core_pipeline()`、`ArtifactPaths` 和各 writer。以源码确定 fresh parse 的输出；`outputs/final_structure_regression/case_002` 只作实物交叉检查。未改生产代码、文件名或目录。R3-B15 已确认 PDFFast 自有中间 JSON 的 fresh runtime file bus 为零；“有文件”不等于“下一阶段靠文件驱动”。

## 1. 分类口径与最终产品

| 类别 | 含义 | 本轮判断 |
|---|---|---|
| A USER_PRODUCT | 调用方消费的业务结果 | `ParseResult` 的 `canonical`、`markdown`；`result/document.json`、`result/document.md`、`result/manifest.json` |
| B AUDIT_OBSERVABILITY | 可解释质量、边界和 provenance 的结果 | `ParseResult.audit`、`result/audit.json`、Quality/Evidence、render manifest、执行 manifest、日志 |
| C INTERNAL_DIAGNOSTIC | 深度调试或算法观察 | Profiler 明细、结构/表格/TextFlow 中间视图、probe crops、任务输入图像 |
| D PROVIDER_PERSISTENCE | Provider 执行及选择证据 | raw task JSON、runtime manifest、selected wrappers/index、execution manifest、Provider 自身文件 |
| E REPLAY_COMPATIBILITY | 旧 file API、回归或离线复核仍需的产物 | Stage 命名 JSON/JSONL/Markdown、selected 文件、Canonical/renderer/audit 历史路径 |
| F BENCHMARK_TEST_ONLY | 基准、fixture、人工比较 | `tests/fixtures`、`outputs/*review*`、`outputs/final_structure_regression` 的额外 review 文件 |
| G CONFIG_POLICY | 解析前配置，非 parse 输出 | `configs/providers.json`、打包同名资源、frozen route candidates、模型/manifest 校验输入 |
| H LEGACY_REDUNDANT | 已证明无消费者/诊断价值才可考虑删除 | 本轮**没有证明任何已写产物满足该严格条件**；仅列复核候选 |

分类可叠加。用户通常应消费内存中的 `ParseResult.canonical` 与 `.markdown`，需要落盘时使用稳定的 `result/document.json` 与 `result/document.md`；`ParseResult.audit` / `result/audit.json` 用于质量和结构边界核验，`result/manifest.json` 是路径索引。大量写出的 Stage 文件是证据与兼容资产，不是等价的用户产品协议。HTTP adapter 实际响应也只含 Markdown、Canonical、Audit 和 run id。

## 2. Fresh parse 完整输出树

以下目录以 `<output_root>/<run_id>/` 为根。`[]` 表示条件产生，`*` 表示随页/任务数变化。**所有 `output_mode` 都写这些适用文件**；模式只控制 `ParseResult.artifacts` 暴露的路径，不负责减少写盘。样本目录中的 `pipeline_report.md`、`review_metrics.json`、`prediction_reuse_validation.json` 是额外评审产物，非以下 production writer 的固定输出。

```text
<run>/
  result/
    document.json                 # A Canonical 1.1 稳定副本
    document.md                   # A 最终可读/LLM-ready Markdown
    audit.json                    # B 正式结构/语义边界审计副本
    manifest.json                 # A/B run_id、case_id、模式、结果路径索引
  diagnostics/logs/
    [pipeline.log]                # B/C；capture_output=True 或失败记录时
  01_stage1/
    page_profile.json             # B/C/E Native 页面画像
    page_snapshot.jsonl           # C/E Native 逐页原始观察
  03_stage3/
    section_alignment.json        # B/C/E 通用章节发现/页面归属；非模板对齐
  04_stage4/
    page_structure.json           # C/E 页面区块结构
  05_stage5/
    result.json                   # C/E 表格恢复机器结果
    result.md                     # C/E 表格恢复视图
    logical_tables.md             # C/E 跨页逻辑表视图
  06_stage6/
    noise_candidates.json/.md     # C/E 噪声候选
    reading_order.json/.md        # C/E 阅读顺序
    paragraphs.json/.md           # C/E 段落恢复
    cross_page_paragraphs.json/.md# C/E 跨页段落
    normalized_text_flow.json/.md # B/C/E Native 最终文本流和 provenance
    readable_final.md             # C/E Native-only 阅读视图；非最终产品
  07_stage7/
    evidence_manifest.json/.md    # B/E 内容/区域/页面 accounting 与 provenance
  08_stage8/
    quality_gate.json/.md         # B/E 质量决策及 fallback 原因
    probe_crops/*.png             # C；按需探测图像
  09_1_fallback_units/
    fallback_execution_manifest.json/.md # B/C/E fallback task 输入契约
    inputs/{page,region,inline}/*        # C/D；按任务产生的 Provider 输入图像
  09_2_provider_plan/
    provider_plan.json/.md        # B/C/E capability 路由计划
  09_6_3_runtime_policy/
    runtime_escalation_policy.json/.md # B/C/E frozen policy 的执行计划
  09_8_production_fallback/
    production_execution_manifest.json  # B/D/E 执行波次、统计、选择索引
    selected_prediction_index.json      # D/E task → selected wrapper 路径
    selected_predictions/<task_id>.json # D/E 每 task 尝试、normalized prediction、终态
    [provider_raw/<task_id>.json]       # D/E raw task envelope；成功调用 normalizer 时
    [provider_raw/runtime_manifest.json]# D/E normalizer 的运行 manifest；有调用时
    [Provider-owned output files]       # D；worker/adapter 产物，依配置和任务变化
  10_1_canonical/
    canonical_document.json       # A/B/E 与 result/document.json 同次对象的历史副本
  10_2_llm_ready/
    llm_ready.md                   # A/E 与 result/document.md 同次字符串的历史副本
    render_manifest.json          # B/E 渲染检查、record dispositions、路径
  10_2_1_structure_audit/
    structure_boundary_audit.json # B/E 与 result/audit.json 同次审计的历史副本
```

没有正式 `02_stage2/` writer；旧 Template 分析已取消。没有独立、固定的 production `normalized_prediction.json`：normalizer 的 dict 进入 executor 的 attempts/selected wrapper，随 selected JSON 持久化。失败/超时、空任务、不同 Provider 能力会改变 raw 文件和图像数量。`capture_output=False` 时成功路径可能不生成日志文件；异常且启用捕获时会追加 traceback。`run_pipeline` 脚本调用同一个 Parser，不另建一套输出树；其 `--from-artifacts` 仅出现在提示中，当前未启用。

## 3. 按语义审视各组 Artifact

| 当前文件/组 | 首要职责 | 长期保留理由及迁移注意 |
|---|---|---|
| `page_profile.json`、`page_snapshot.jsonl` | Native Observation/Profiler 诊断 | snapshot 保存逐页可追溯观察；旧 Native file API 和 parity 依赖，改名需兼容 |
| `section_alignment.json` | observed heading、section 与页面归属 | 名称仍含旧 aligner 语气，实际由 generic `run_section_discovery` 写出；结构证据需保留 |
| `page_structure.json` | Native 区块结构 | 表格与 TextFlow 诊断/旧入口依赖，非用户最终章节协议 |
| Stage5 `result.json/.md`、`logical_tables.md` | 表格恢复和跨页逻辑表 | 原表格证据及阅读视图，适于长期可复核，不是最终文档 |
| Stage6 五组 JSON/Markdown、`readable_final.md` | Native TextFlow 的噪声/顺序/段落/最终 Native 流 | `normalized_text_flow.json` 具较高 provenance 价值；`readable_final.md` 是 Native-only，不能与最终 `document.md` 混同 |
| Evidence JSON/Markdown | 原生证据 accounting 和 provenance | 质量/审计解释的关键证据；保留 |
| Quality JSON/Markdown、probe crops | 决策与触发理由；可视化诊断 | Quality decision 是正式可解释信息；probe crops 是 debug，不是用户产品 |
| Fallback manifest 与 input images | task 形成/执行输入 | 解释为何产生 PAGE/REGION/INLINE；输入图像又是 Provider 执行资源 |
| Capability/provider plan | capability 路由（尚未指定最终 Provider） | 与 Quality decision 分开；可复核路由原因，不是对用户的质量判定 |
| runtime escalation policy | frozen Provider chain 的执行计划 | Provider 顺序/升级条件证据；属于执行规划及兼容，不等同配置文件本体 |
| raw task、runtime manifest、Provider 原生文件 | 原始 Provider 证据及来源 | 需保留 provider identity、source refs、哈希和可复核性；Provider 原生文件与 PDFFast envelope 分开 |
| selected wrappers、index、execution manifest | 每 task 的选中/未解决结果及尝试轨迹 | Canonical 归因与 replay 依赖；即使空/失败也有终态意义 |
| Canonical/Markdown/renderer/audit 历史路径 | 最终结果的内部副本、渲染/审计证据 | 当前 file API/CLI、测试、人工流程可能引用；不能因 `result/` 副本出现就直接删 |

`result/document.json` 当前 `schema_version=1.1`，包含 pages、sections、records、`document_units` 和 fallback overlays；可视为机器可读的正式 Canonical Result。它仍含 `stage`/`substage` 及 source/artifact metadata，不能把“路径稳定”误解为可任意改变 schema。应长期保留 `result/document.json` 路径，并按既有 schema 契约演进。`result/document.md` 是同次 renderer 字符串的正式可读/模型可读产物；`10_2_llm_ready` 的编号对用户结果没有语义必要性，只是现有兼容路径。`result/audit.json` 是当前正式审计文件，其 `validation.pass` 可用于结构边界判断；内部 `structure_boundary_audit.json` 是同一审计的历史路径。fresh runner **不**写 `audit.md`；Audit CLI 可生成 Markdown 视图。未来是否暴露摘要或 `audit.md` 是单独产品决策，不能在本轮宣称现有协议已有该文件。

## 4. DocumentUnit 与开发诊断

Fresh `run_stage10` 在内存中执行 recovered heading candidates → adjudication → preview → anchor admission → page relations/coverage → `DocumentUnit` reconciliation。正式持久化落点是 Canonical 1.1 的 `document_units`，并体现在 Markdown 与 Audit 的 `document_unit_audit`。当前 `ArtifactPaths` 和 runner **没有**为候选、裁决、preview、admission、coverage 各写一个生产 JSON 的路径；这些中间对象主要由 unit/regression、`docs/reviews` 和人工 review 流程检查。不得因为开发资料里有这些名字，就把它们列成每次 parse 的正式输出。

`tests/fixtures/artifacts`、reference-bound 样本、`outputs/template_removal_review`、`outputs/final_structure_regression` 的额外 summary/report/metrics/comparison 文件属 F。`result/` 与 Stage sidecars 出现在这些目录时仍是 parser 产物；旁边的评审文件不是固定 parser 契约。`configs/providers.json`、bundled providers、frozen route candidate JSON 及模型 manifest 属 G，不在 `<run>/` 下，也不应为追求 object-driven 而删除。

## 5. Stage 名称残留与硬编码依赖

实际目录只有 `01_stage1`、`03_stage3`、`04_stage4`、`05_stage5`、`06_stage6`、`07_stage7`、`08_stage8`、`09_1_fallback_units`、`09_2_provider_plan`、`09_6_3_runtime_policy`、`09_8_production_fallback`、`10_1_canonical`、`10_2_llm_ready`、`10_2_1_structure_audit`。`02_stage2` 只在历史文档出现，fresh 不生成。目录编号表达旧迁移顺序，已不准确表达现有 object-driven 责任；尤其 `03_stage3/section_alignment` 已变成 generic section discovery，`09_8_production_fallback` 同时包含执行、selection 与持久化，`10_2_llm_ready` 只是最终 Markdown 的历史副本。

| 历史 Stage 词 | 当前实际职责/残留 | 失真或保留原因 |
|---|---|---|
| Stage1 | Profiler 的 profile/snapshot，source refs 如 `stage1:image:*` | Native Observation；source ref 是现有证据身份，不能简单重写 |
| Stage2 | 旧 Template 文档/术语，无 fresh 目录 | 已取消的架构，不应作为新输出层级 |
| Stage3 | `section_alignment.json`、回归路径 | Generic Section Discovery，不再对齐固定模板 |
| Stage4 | `page_structure.json`、`stage4:block:*` refs、Native 函数与诊断 | Page Structure；ref/JSON 字段是兼容身份 |
| Stage5 | 表格恢复 `result.*`、TextFlow/Evidence 参数 `stage5_path` | Table Recovery；`result.json` 泛名依赖目录解释 |
| Stage6 | noise/order/paragraph/normalized flow、`readable_final.md`、Audit/Canonical Stage6 文案 | Native TextFlow；不是最终用户文档 |
| Stage7 | Evidence JSON/Markdown、Stage7 provenance | Evidence accounting；编号不是新对象边界 |
| Stage8 | Quality JSON/Markdown、fallback 中 `stage8_decision` 字段 | Quality decision；字段已进入任务/Canonical 语义，迁移需 schema 评审 |
| Stage9 | fallback、capability、frozen policy、Provider execution/selection、`s9_*` task id、配置名 | 单个 Stage 词已覆盖多种职责；policy/task id 不能为目录美化修改 |
| Stage10 | `_stage10_*` 文件/CLI、`run_stage10`、Canonical/Markdown/Audit metadata | Canonical assembly、Render、Audit 三类职责；历史 CLI/file API 仍需兼容 |

| 曝露面 | 实例 | 未来处理原则 |
|---|---|---|
| 用户可见 A / public API B | `result/`、`ParseResult.artifacts`；`full` 暴露全部 `ArtifactPaths`，`run_id` 目录可手工浏览；`result/manifest.json` 指向稳定路径 | `minimal`/`diagnostic` 基本遮蔽 Stage；`full` 和手工文件流程仍泄漏路径 |
| 内部生产 C | `pipeline/artifacts.py` 14 个编号目录；`runner.py` 的 `run_stage10`、`_stage10_builder.py`、`_stage10_renderer.py`、`_stage10_audit.py`；Evidence 的 `stage5_path`/`stage6_dir` | 优先语义化内部表达，但不能顺手改 schema/provenance/算法 |
| 兼容 D | Native/Evidence/Normalizer/Canonical/Renderer/Audit file APIs 与 CLI 参数 `--native-flow`、`--quality-gate`、`--selected-index` 等 | 保留旧路径和参数别名；静态 path 字符串之外还要考虑 JSON 内嵌路径、source refs、hash |
| 测试/benchmark E | 多个 regression fixture 直接拼 `06_stage6`、`09_8_production_fallback`；`tools/migration` 两个文件引用编号目录 | 迁移须逐项测 byte/parity；benchmark 文件引用视为事实上的兼容消费者 |
| 历史文档 F | `docs/PIPELINE.md`、`OUTPUT_MODES_ZH.md`、大量 `docs/reviews`、README 中旧 Stage 叙述 | 新文档可用语义名称，历史审计文档保留时代语境；避免改写历史证据 |

静态计数（新增本报告前的 `rg -l -F` 快照；**每格为含该字面目录名的文件数**，不含 `outputs/`、`.git/`；列分别为 `pdffast/tests/scripts/docs/README/configs`。本报告本身引用这些目录，重跑时 docs 列会增加）：

| 目录 | production | tests | scripts | docs | README | configs |
|---|---:|---:|---:|---:|---:|---:|
| `01_stage1` | 1 | 2 | 0 | 7 | 0 | 0 |
| `02_stage2` | 0 | 0 | 0 | 1 | 0 | 0 |
| `03_stage3` | 1 | 10 | 0 | 7 | 0 | 0 |
| `04_stage4` | 1 | 2 | 0 | 4 | 0 | 0 |
| `05_stage5` | 1 | 2 | 0 | 3 | 0 | 0 |
| `06_stage6` | 1 | 15 | 0 | 5 | 0 | 0 |
| `07_stage7` | 1 | 3 | 0 | 1 | 0 | 0 |
| `08_stage8` | 1 | 6 | 0 | 4 | 0 | 0 |
| `09_1_fallback_units` | 1 | 1 | 0 | 1 | 0 | 0 |
| `09_2_provider_plan` | 1 | 7 | 0 | 3 | 0 | 0 |
| `09_6_3_runtime_policy` | 1 | 2 | 0 | 1 | 0 | 0 |
| `09_8_production_fallback` | 1 | 11 | 0 | 4 | 0 | 0 |
| `10_1_canonical` | 1 | 3 | 0 | 3 | 0 | 0 |
| `10_2_llm_ready` | 1 | 4 | 0 | 3 | 0 | 0 |
| `10_2_1_structure_audit` | 1 | 1 | 0 | 2 | 0 | 0 |

这些计数只覆盖**完整目录字面量**，不含 `Stage6` 文案、`stage6_*` JSON 字段、`stage4:block:*`/`stage1:image:*` provenance ref、`s9_...` task id、frozen 配置文件名、嵌入 JSON metadata、输出树/外部仓库。另一轮静态搜索显示 `Stage1`～`Stage10` 词汇广泛存在于 Native 大文件、Audit/Canonical 错误信息、CLI 描述、测试和历史文档；并非只改 `ArtifactPaths` 就能清除。尤其 `stage`/`substage`、`stage10_resolution`、source refs、task id 和 frozen policy 文件名具有 schema/回归身份，不能作为单纯目录美化替换。Python 文件名中的 `_stage10_*` 是内部实现兼历史 file CLI；`run_stage10` 是内部兼容入口，不属于 `PDFFastParser` 公共方法。`README`、`docs/PIPELINE.md` 的 Stage 叙述已有过时成分，未来文档更新应基于新职责，不改变旧测试 fixture。

## 6. 兼容风险与 ParseResult 遮蔽程度

仓库内确定消费者：`ArtifactPaths` writer、回归/契约测试、`tools/migration`、独立 file API/CLI、render manifest/Canonical provenance 中的历史路径字符串，以及 `full` 模式的 `ParseResult.artifacts`。`docs/INTEGRATION_ZH.md` 推荐业务系统只保存 `result_manifest` 和稳定 `result/` 路径；这降低**按建议接入者**的迁移成本。实际 JudgeAI、其他 Python 调用方、shell 脚本、人工运维是否直接读取编号目录，仓库无法证明：**UNKNOWN EXTERNAL DEPENDENCY**。不能因为 `scripts/run_pipeline.py` 没有字面编号目录就断言外部无人依赖。

`ParseResult` 默认给 `canonical`、`markdown`、`audit` 对象及五个 `result/` 路径；`diagnostic` 再暴露日志；`full` 通过 `ArtifactPaths.as_dict()` 暴露所有 Stage 路径。因而它能遮蔽**日常 API 用法**的大部分目录结构，但不能屏蔽 `full`、内部路径/provenance、手工文件消费者。`result/manifest.json` 只指向稳定 `result/` 路径（另含可选日志），未把所有 Stage 路径公布为结果索引。重命名风险最大的是**旧文件路径同时被测试/脚本/外部流程与 JSON provenance 引用**；若改变字节级路径还会改变 hash/parity，即使正文内容不变。

## 7. 未来布局与唯一 R4-B 建议

建议的**概念布局**（不实施、不承诺立即移动旧路径）：

```text
<run>/result/       # Canonical、Markdown、正式 audit 和索引，保持现路径
<run>/observability/# Quality/Evidence、render/production summary、provenance
<run>/diagnostics/  # Native 明细、probe crops、日志、开发视图
<run>/providers/    # raw、selected、native outputs 与 task images
<run>/<legacy Stage dirs>/ # 渐进兼容视图/历史路径，迁移期继续可用
```

现有 `minimal/diagnostic/full` 是**路径可见性**，不是存储级别。未来若要 `minimal / standard / debug`：`minimal` 可只承诺 `result/`；`standard` 附 Audit、Quality 摘要和关键 provenance；`debug` 保留完整证据、Provider 与 Native 文件。但必须另行定义写盘/保留策略，并在确认 replay、审计、Provider 原生引用、外部消费者后才能减少产物；不能把现有 `minimal` 误说成只写两个文件。

**唯一推荐的 R4-B：在现有 `ArtifactPaths` 上建立语义化 artifact catalog/分组视图，保持所有实际路径、文件内容与旧属性不变。** 先把 A–G 角色、固定与条件产物、公开/内部属性、writer 所有者和兼容别名集中为可检查契约；覆盖 `result/`、Native、Quality、Provider、renderer/audit，并用不启动重型 Provider 的 contract test 验证现有路径逐项不变。理由：编号目录字面量在生产代码主要集中于 `ArtifactPaths`，但动态文件名、JSON 内嵌路径、测试和 file CLI 分散；先定义语义身份与稳定性等级，才能在后续小步改目录时清楚保留哪些旧路径。R4-B 不改解析算法、Canonical schema、Markdown、Provider selection 或 object-driven handoff，不拆 runner，也不一次性重命名 Stage1～10。

## 验证口径

本轮仅源码/样本树静态检查、`rg`/`find` 和 `git diff --check`；**未运行 pytest**。冻结基线 full `311 passed / 20 skipped / 0 failed`、reference-bound `331 passed / 0 failed` 是用户提供的此前结果，不是本轮结果。
