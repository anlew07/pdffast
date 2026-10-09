# Final Structure Regression — case_001～case_005

日期：2026-09-29。结论：**PASS，冻结当前 Document Structure baseline**。五份真实 PDF 都由当前 `run_core_pipeline` 从原 PDF 重新计算 Native、Evidence、Quality、Fallback Planning、Canonical、Renderer 和 Audit；五份结构 Audit 均为 PASS。Provider 执行阶段经逐 task 契约核对后，复用既有 selected predictions，没有重新启动重型 Provider。此结论验证当前结构与既有 Provider 结果的集成；不声称重新验证 Provider worker 的实际运行。

## 执行方式与边界

- 输入：`/Users/admin/Workspace/pdffast/benchmark/samples/real/case_001.pdf` ～ `case_005.pdf`，PDF 未复制。
- 输出：`outputs/final_structure_regression/case_001/` ～ `case_005/`，每例有 `result/document.json`、`result/document.md`、`result/audit.json`、`result/manifest.json`、Stage 1～10 诊断文件、`pipeline_report.md`、`review_metrics.json` 和 `prediction_reuse_validation.json`。历史 `outputs/template_removal_review/` 未覆盖。
- 临时验收脚本 `_run_replay.py` 在当前 runner 的 Provider 执行点复用旧结果。只有新旧 task 的 ID、类型、页码、source ID、capability route、provider chain、output contract 和 terminal fallback **按原顺序完全相等**才允许复用。五例均 PASS；所有 selected prediction 文件内容与历史结果相等。脚本没有修改生产代码。
- Stage 1 page profiles 相等，snapshot SHA256 相等；Stage 5 所有 `pages` 相等；Stage 6 record ID/顺序、去掉章节元数据后的完整 records 相等；Evidence `summary` 相等；Fallback tasks 除新的输入图片路径外完整相等；selected provider、terminal 状态和 prediction payload 相等；Canonical 去掉章节元数据后的 records 相等。五例均满足。

## 总表

| Case | Pages | Native sections | Unresolved 页段 | DocumentUnits | PARTIAL / RESOLVED | Fallback tasks | Stage 5 tables | TextFlow records | Audit | 人工抽检 |
|---|---:|---:|---|---:|---:|---:|---:|---:|---|---|
| [001](../../outputs/final_structure_regression/case_001/pipeline_report.md) | 30 | 11 | 1, 18, 20–30 | 0 | 0 / 0 | 19 | 24 | 243 | PASS | PASS |
| [002](../../outputs/final_structure_regression/case_002/pipeline_report.md) | 16 | 10 | 1 | 0 | 0 / 0 | 1 | 13 | 71 | PASS | PASS |
| [003](../../outputs/final_structure_regression/case_003/pipeline_report.md) | 66 | 16 | 1, 21–23, 25–27, 29–64, 66 | 5 | 3 / 2 | 54 | 41 | 631 | PASS | PASS |
| [004](../../outputs/final_structure_regression/case_004/pipeline_report.md) | 114 | 15 | 1, 21–24 | 0 | 0 / 0 | 92 | 18 | 295 | PASS | PASS |
| [005](../../outputs/final_structure_regression/case_005/pipeline_report.md) | 20 | 10 | 1, 16–20 | 0 | 0 / 0 | 6 | 12 | 65 | PASS | PASS |

`Stage 5 tables` 是 Stage 5 `pages[].items` 中 `type=table` 的数量，不等同于 TextFlow 的 `table_ref` 数量。各例的完整章节标题、anchor page、页范围以及 DocumentUnit 字段见各自 `pipeline_report.md`。

## 内容、路由和审计

- Native word accounting 分别为 **0.996494 / 1.0 / 0.997856 / 1.0 / 1.0**，未核算词数分别为 **10 / 0 / 19 / 0 / 0**，与历史运行的 Evidence summary 逐字段相等。Stage 1 快照、表格、TextFlow record 内容与顺序都未减少或重排。
- Fallback task 数 **19 / 1 / 54 / 92 / 6**，task ID、类型、页码/region source、完整任务负载、selected prediction、terminal 状态均与历史相等。terminal preserve 分别为 **3 / 0 / 2 / 0 / 0**；没有因 DocumentUnit reconciliation 改变 Quality / Fallback routing。
- 五份 Audit 的 `validation.pass=True`、`status=PASS`，无 errors、warnings 或失败 checks。Native record / fallback checks 均通过。DocumentUnit audit 五例都是 PASS；case_003 有 5/5 marker、5/5 provenance，去掉 marker 后正文与不含 DocumentUnit 的当前基础渲染完全一致。其余四例 0 marker、body unchanged。
- Canonical records 不含 `document_id` 或 section parent；DocumentUnit 页范围只表示已确认覆盖。PARTIAL 未表述完整边界，RESOLVED 明确标注“非独占”。元数据不是 `#` Section heading。

## 逐例观察

### case_001

11 个 Native sections。附件后的真实标题“《电源学报》2018年度优秀论文名单”保留于 p19；没有模板制造的“附件内容”章节。p18 从旧的“九、审核意见”页范围移为 unresolved，但该页 IEEE 奖项的整页 fallback 内容仍在 Markdown，正文记录、selected prediction、表格均不变。抽查 p2、p15、p18–20、p30，未见正文丢失或重复。

### case_002

10 个标准主文档章节与旧结果完全一致，p1 unresolved；抽查 p2 信息表、p7 正文、p14 附件清单表和 p1 region fallback。Markdown 与历史结果字节相同。

### case_003

p19、p20、p24 三个同名“关于国家自然科学基金资助项目批准及有关事项的通知”是三个独立 Native section，没有按 title 去重。p21–23、p25–27、p29–64、p66 保持 unresolved 的 Native 结构标记；p21–23 OCR 正文、p43–59 layout fallback、p64–66 附件内容仍可读。p27、p29、p30、p36、p66 五个 recovered DocumentUnit 的标题和锚点与页内已选 Provider 文字一致。p27/p30/p36 为 PARTIAL；p29/p66 为 RESOLVED（非独占）。五个 DocumentUnit 均未被当成 Section，亦未覆盖 p28/p65 的 Native section。抽查上述页段，未见错误吞页、重复正文或虚构标题。去掉五个边界 marker 后，Markdown 与历史结果字节相同。

### case_004

p25、p48、p80、p90、p101 五个编号重启标题现成为 Native section；p101 的“五、规范标准”延续到 p114。p21–24 继续 unresolved，但 p21“科研成果证明材料”封面和后续目录/材料内容仍在。p83 与 p108 的 fallback OCR 内容仍在 p80–89、p101–114 对应章节内；当前 admission 在有 Native section 归属的页不提升 recovered DocumentUnit，故本例为 0 个，这是本轮允许的保守结果。抽查 p21–25、p48、p80–83、p90、p101–114，未见内容丢失或重复。Markdown 与历史版的唯一区别，是五行原有正文标题提升为 `#` section heading 并移动到对应 `source-page` 注释之前；无新增正文。p80 原 PDF 的标题被分页拆为“...证明材”及 p81 的“料”，section title 保留 p80 可见部分；末字仍在 p81 正文。这是可见的标题完整性限制，不导致内容丢失或错误页范围。

### case_005

主文档 10 个章节稳定；p16–20 附件结构证据不足，继续 unresolved。抽查 p13 表格、p15 主文档结尾、p16–20 扫描附件，fallback 文字仍在。Markdown 与历史结果字节相同。

## 测试与冻结判断

- `.venv/bin/pytest -q tests/unit tests/contracts tests/regression`：**269 passed, 4 failed, 15 skipped**。
- reference-bound（设置 `PDFFAST_REFERENCE_ROOT` 与 `PDFFAST_SAMPLE_PDF` 后同一命令）：**284 passed, 4 failed**。
- 四个失败均为已知的 `tests/unit/test_provider_lifecycle.py` 子进程清理测试，与本轮结构验收无关；本轮未修改 Provider lifecycle。`uv run` 在当前沙箱无法访问原 uv cache，改用临时缓存时又因无法联网获取 `hatchling` 失败，因此使用现成 `.venv` 运行同一 pytest 测试集。

**冻结结论：PASS。** 将 Generic Native Section Discovery、Recovered Document Structure、Canonical DocumentUnit 1.1、DocumentUnit Renderer 和 DocumentUnit Audit 作为当前结构基线。只在新真实 PDF 出现明确解析 regression 时重开结构算法。下一阶段应单独处理上述四个 Provider lifecycle 测试失败；本轮不进入该工作。
