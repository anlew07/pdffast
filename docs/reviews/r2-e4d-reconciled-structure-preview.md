# R2-E4D Structure Reconciliation Preview — case_003

这是开发审阅视图。输入为现有 Stage 3 Native section alignment 和 E4C proposal；未运行 Provider，也未写入 Canonical、Renderer、Audit 或原有 Stage Artifact。

## 输入与边界

- Native: `outputs/template_removal_review/case_003/03_stage3/section_alignment.json`。
- E4C: 从 `outputs/template_removal_review/case_003/06_stage6/normalized_text_flow.json` 和现有 selected predictions 只读重建；46 个 heading candidates，41 个 proposals。
- 规则：Native 可靠归属优先；仅 ACCEPTED_PROPOSAL 且角色为 DOCUMENT_BOUNDARY_CANDIDATE 或 SECTION_CANDIDATE 可形成单页 recovered anchor。Anchor 不赋予 section_id，不推断 range。

## 概览

- Native sections：16，全部原样保留。Native 已归属页：22。
- Native unresolved regions：5；unresolved 页：44，全部仍保持 unresolved。
- E4C 决策：5 ACCEPTED_PROPOSAL、25 AMBIGUOUS、11 REJECTED。Preview：5 个 recovered document anchors、0 个 recovered section anchors、0 个 conflict。
- 没有 preview anchor 的 unresolved 页：39。有 anchor 的 5 页也仍是 Native unresolved；这里的“39”只表示没有候选 anchor，不表示另外 5 页已经完成归属。

## Native sections（保持原样）

| Native ID | 原始标题 | 页范围 | Anchor 页 |
|---|---|---:|---:|
| observed_section_001 | 一、基本信息 | 2–2 | 2 |
| observed_section_002 | 二、项目负责人基本情况 | 3–6 | 3 |
| observed_section_003 | 三、拟开展研究内容 | 7–7 | 7 |
| observed_section_004 | 四、研究条件 | 8–8 | 8 |
| observed_section_005 | 五、项目人员情况 | 9–11 | 9 |
| observed_section_006 | 六、项目进度计划（说明项目进度，包括实施方案、实施地点等内容） | 12–12 | 12 |
| observed_section_007 | 七、项目绩效目标 | 13–14 | 13 |
| observed_section_008 | 八、附件清单 | 15–15 | 15 |
| observed_section_009 | 科研诚信承诺书 | 16–16 | 16 |
| observed_section_010 | 九、审核意见 | 17–17 | 17 |
| observed_section_011 | 证明材料目录 | 18–18 | 18 |
| observed_section_012 | 关于国家自然科学基金资助项目批准及有关事项的通知 | 19–19 | 19 |
| observed_section_013 | 关于国家自然科学基金资助项目批准及有关事项的通知 | 20–20 | 20 |
| observed_section_014 | 关于国家自然科学基金资助项目批准及有关事项的通知 | 24–24 | 24 |
| observed_section_015 | 红外物理国家重点实验室 | 28–28 | 28 |
| observed_section_016 | 军民融合及产学研合作证明 | 65–65 | 65 |

## 5 个已接受 proposal 的去向

| 页 | Proposal ID | 原始 title parts（按原顺序） | 建议角色 | Preview 结果 | Range | 冲突 |
|---:|---|---|---|---|---|---|
| 27 | `recovered:p0027:01` | 陕西省自然科学基础研究计划<br>项目合同（任务）书 | DOCUMENT_BOUNDARY_CANDIDATE | recovered_document_anchor | UNRESOLVED | 无 |
| 29 | `recovered:p0029:01` | 陕西省教育厅服务地方专项计划项目<br>合同书 | DOCUMENT_BOUNDARY_CANDIDATE | recovered_document_anchor | UNRESOLVED | 无 |
| 30 | `recovered:p0030:01` | 陕西省自然科学基础研究计划项目<br>结题审查结果的通知 | DOCUMENT_BOUNDARY_CANDIDATE | recovered_document_anchor | UNRESOLVED | 无 |
| 36 | `recovered:p0036:01` | 陕西省国际科技合作基地<br>项目协议书 | DOCUMENT_BOUNDARY_CANDIDATE | recovered_document_anchor | UNRESOLVED | 无 |
| 66 | `recovered:p0066:01` | 科技成果登记表<br>(基础理论、软科学类成果) | DOCUMENT_BOUNDARY_CANDIDATE | recovered_document_anchor | UNRESOLVED | 无 |

5 个 proposal 的 title parts 和 candidate refs 均逐项保留，没有把组合标题拆成多个 section，也没有补写 PDF 中不存在的标题。

| 页 | candidate refs | Provider / 证据 |
|---:|---|---|
| 27 | `p0027:s9_0027_page_fallback_0260f9ae5126:0007`<br>`p0027:s9_0027_page_fallback_0260f9ae5126:0008` | rapidocr_ch_light / OCR_VISUAL_LINE |
| 29 | `p0029:s9_0029_page_fallback_9ca6452f49a8:0009`<br>`p0029:s9_0029_page_fallback_9ca6452f49a8:0010` | rapidocr_ch_light / OCR_VISUAL_LINE |
| 30 | `p0030:s9_0030_page_fallback_9ea797c3cdd5:0011`<br>`p0030:s9_0030_page_fallback_9ea797c3cdd5:0012` | rapidocr_ch_light / OCR_VISUAL_LINE |
| 36 | `p0036:s9_0036_page_fallback_e2a7405350fc:0014`<br>`p0036:s9_0036_page_fallback_e2a7405350fc:0015` | rapidocr_ch_light / OCR_VISUAL_LINE |
| 66 | `p0066:s9_0066_page_fallback_7fd06c196caf:0042`<br>`p0066:s9_0066_page_fallback_7fd06c196caf:0043` | rapidocr_ch_light / OCR_VISUAL_LINE |

## Native unresolved 与 page 29

| 原始 unresolved 区间 | 原因 | Preview anchor 页 |
|---|---|---|
| 1–1 | 首个已观察章节标题之前的页面没有可靠章节边界。 | 无 |
| 21–23 | 视觉标题后的页面缺少可靠的章节延续证据。 | 无 |
| 25–27 | 视觉标题后的页面缺少可靠的章节延续证据。 | 27 |
| 29–64 | 视觉标题后的页面缺少可靠的章节延续证据。 | 29, 30, 36 |
| 66–66 | 最后一个已观察标题之后缺少可靠的章节延续证据。 | 66 |

page 29：Native `section_id=None`，属于 29–64 unresolved region。E4C 的 `recovered:p0029:01` 把“陕西省教育厅服务地方专项计划项目”和“合同书”作为同一个 composite proposal；Preview 仅创建 `recovered_document_anchor`，`source=RECOVERED`，`range_status=UNRESOLVED`，`page_range=None`。page 30、31 等页没有被划给它。

## 逐页对照

“Native 归属”来自 Stage 3，始终不被 preview 修改；“proposal”含同页的 E4C 决策摘要。

| 页 | Native 归属 | Recovered proposal | Preview 决策 | 冲突 | 原因 |
|---:|---|---|---|---|---|
| 1 | unresolved / `section_id=None` | 无 | 继续 unresolved | 无 | 无 recovered proposal |
| 2 | `observed_section_001` / 一、基本信息 | 无 | 保留 Native | 无 | Native section ownership remains authoritative |
| 3 | `observed_section_002` / 二、项目负责人基本情况 | 无 | 保留 Native | 无 | Native section ownership remains authoritative |
| 4 | `observed_section_002` / 二、项目负责人基本情况 | 无 | 保留 Native | 无 | Native section ownership remains authoritative |
| 5 | `observed_section_002` / 二、项目负责人基本情况 | 无 | 保留 Native | 无 | Native section ownership remains authoritative |
| 6 | `observed_section_002` / 二、项目负责人基本情况 | 无 | 保留 Native | 无 | Native section ownership remains authoritative |
| 7 | `observed_section_003` / 三、拟开展研究内容 | 无 | 保留 Native | 无 | Native section ownership remains authoritative |
| 8 | `observed_section_004` / 四、研究条件 | 无 | 保留 Native | 无 | Native section ownership remains authoritative |
| 9 | `observed_section_005` / 五、项目人员情况 | 无 | 保留 Native | 无 | Native section ownership remains authoritative |
| 10 | `observed_section_005` / 五、项目人员情况 | 无 | 保留 Native | 无 | Native section ownership remains authoritative |
| 11 | `observed_section_005` / 五、项目人员情况 | 无 | 保留 Native | 无 | Native section ownership remains authoritative |
| 12 | `observed_section_006` / 六、项目进度计划（说明项目进度，包括实施方案、实施地点等内容） | 无 | 保留 Native | 无 | Native section ownership remains authoritative |
| 13 | `observed_section_007` / 七、项目绩效目标 | 无 | 保留 Native | 无 | Native section ownership remains authoritative |
| 14 | `observed_section_007` / 七、项目绩效目标 | 无 | 保留 Native | 无 | Native section ownership remains authoritative |
| 15 | `observed_section_008` / 八、附件清单 | 无 | 保留 Native | 无 | Native section ownership remains authoritative |
| 16 | `observed_section_009` / 科研诚信承诺书 | 无 | 保留 Native | 无 | Native section ownership remains authoritative |
| 17 | `observed_section_010` / 九、审核意见 | 无 | 保留 Native | 无 | Native section ownership remains authoritative |
| 18 | `observed_section_011` / 证明材料目录 | 无 | 保留 Native | 无 | Native section ownership remains authoritative |
| 19 | `observed_section_012` / 关于国家自然科学基金资助项目批准及有关事项的通知 | 无 | 保留 Native | 无 | Native section ownership remains authoritative |
| 20 | `observed_section_013` / 关于国家自然科学基金资助项目批准及有关事项的通知 | 无 | 保留 Native | 无 | Native section ownership remains authoritative |
| 21 | unresolved / `section_id=None` | `recovered:p0021:01` AMBIGUOUS<br>`recovered:p0021:02` REJECTED | 继续 unresolved | 无 | 无 accepted structural anchor |
| 22 | unresolved / `section_id=None` | `recovered:p0022:01` REJECTED | 继续 unresolved | 无 | 无 accepted structural anchor |
| 23 | unresolved / `section_id=None` | `recovered:p0023:01` AMBIGUOUS | 继续 unresolved | 无 | 无 accepted structural anchor |
| 24 | `observed_section_014` / 关于国家自然科学基金资助项目批准及有关事项的通知 | 无 | 保留 Native | 无 | Native section ownership remains authoritative |
| 25 | unresolved / `section_id=None` | 无 | 继续 unresolved | 无 | 无 recovered proposal |
| 26 | unresolved / `section_id=None` | `recovered:p0026:01` REJECTED<br>`recovered:p0026:02` REJECTED<br>`recovered:p0026:03` REJECTED | 继续 unresolved | 无 | 无 accepted structural anchor |
| 27 | unresolved / `section_id=None` | `recovered:p0027:01` ACCEPTED_PROPOSAL | recovered_document_anchor | 无 | accepted composite visual title; only anchor, range unresolved |
| 28 | `observed_section_015` / 红外物理国家重点实验室 | 无 | 保留 Native | 无 | Native section ownership remains authoritative |
| 29 | unresolved / `section_id=None` | `recovered:p0029:01` ACCEPTED_PROPOSAL | recovered_document_anchor | 无 | accepted composite visual title; only anchor, range unresolved |
| 30 | unresolved / `section_id=None` | `recovered:p0030:01` ACCEPTED_PROPOSAL | recovered_document_anchor | 无 | accepted composite visual title; only anchor, range unresolved |
| 31 | unresolved / `section_id=None` | `recovered:p0031:01` AMBIGUOUS | 继续 unresolved | 无 | 无 accepted structural anchor |
| 32 | unresolved / `section_id=None` | 无 | 继续 unresolved | 无 | 无 recovered proposal |
| 33 | unresolved / `section_id=None` | 无 | 继续 unresolved | 无 | 无 recovered proposal |
| 34 | unresolved / `section_id=None` | 无 | 继续 unresolved | 无 | 无 recovered proposal |
| 35 | unresolved / `section_id=None` | 无 | 继续 unresolved | 无 | 无 recovered proposal |
| 36 | unresolved / `section_id=None` | `recovered:p0036:01` ACCEPTED_PROPOSAL | recovered_document_anchor | 无 | accepted composite visual title; only anchor, range unresolved |
| 37 | unresolved / `section_id=None` | 无 | 继续 unresolved | 无 | 无 recovered proposal |
| 38 | unresolved / `section_id=None` | `recovered:p0038:01` AMBIGUOUS | 继续 unresolved | 无 | 无 accepted structural anchor |
| 39 | unresolved / `section_id=None` | `recovered:p0039:01` AMBIGUOUS | 继续 unresolved | 无 | 无 accepted structural anchor |
| 40 | unresolved / `section_id=None` | 无 | 继续 unresolved | 无 | 无 recovered proposal |
| 41 | unresolved / `section_id=None` | `recovered:p0041:01` REJECTED<br>`recovered:p0041:02` REJECTED | 继续 unresolved | 无 | 无 accepted structural anchor |
| 42 | unresolved / `section_id=None` | 无 | 继续 unresolved | 无 | 无 recovered proposal |
| 43 | unresolved / `section_id=None` | `recovered:p0043:01` AMBIGUOUS<br>`recovered:p0043:02` AMBIGUOUS | 继续 unresolved | 无 | 无 accepted structural anchor |
| 44 | unresolved / `section_id=None` | `recovered:p0044:01` AMBIGUOUS<br>`recovered:p0044:02` AMBIGUOUS<br>`recovered:p0044:03` AMBIGUOUS<br>`recovered:p0044:04` AMBIGUOUS | 继续 unresolved | 无 | 无 accepted structural anchor |
| 45 | unresolved / `section_id=None` | 无 | 继续 unresolved | 无 | 无 recovered proposal |
| 46 | unresolved / `section_id=None` | 无 | 继续 unresolved | 无 | 无 recovered proposal |
| 47 | unresolved / `section_id=None` | 无 | 继续 unresolved | 无 | 无 recovered proposal |
| 48 | unresolved / `section_id=None` | 无 | 继续 unresolved | 无 | 无 recovered proposal |
| 49 | unresolved / `section_id=None` | `recovered:p0049:01` AMBIGUOUS | 继续 unresolved | 无 | 无 accepted structural anchor |
| 50 | unresolved / `section_id=None` | 无 | 继续 unresolved | 无 | 无 recovered proposal |
| 51 | unresolved / `section_id=None` | `recovered:p0051:01` AMBIGUOUS<br>`recovered:p0051:02` AMBIGUOUS<br>`recovered:p0051:03` AMBIGUOUS | 继续 unresolved | 无 | 无 accepted structural anchor |
| 52 | unresolved / `section_id=None` | 无 | 继续 unresolved | 无 | 无 recovered proposal |
| 53 | unresolved / `section_id=None` | `recovered:p0053:01` AMBIGUOUS<br>`recovered:p0053:02` AMBIGUOUS<br>`recovered:p0053:03` AMBIGUOUS<br>`recovered:p0053:04` AMBIGUOUS | 继续 unresolved | 无 | 无 accepted structural anchor |
| 54 | unresolved / `section_id=None` | 无 | 继续 unresolved | 无 | 无 recovered proposal |
| 55 | unresolved / `section_id=None` | 无 | 继续 unresolved | 无 | 无 recovered proposal |
| 56 | unresolved / `section_id=None` | `recovered:p0056:01` AMBIGUOUS<br>`recovered:p0056:02` AMBIGUOUS | 继续 unresolved | 无 | 无 accepted structural anchor |
| 57 | unresolved / `section_id=None` | 无 | 继续 unresolved | 无 | 无 recovered proposal |
| 58 | unresolved / `section_id=None` | 无 | 继续 unresolved | 无 | 无 recovered proposal |
| 59 | unresolved / `section_id=None` | `recovered:p0059:01` AMBIGUOUS<br>`recovered:p0059:02` AMBIGUOUS | 继续 unresolved | 无 | 无 accepted structural anchor |
| 60 | unresolved / `section_id=None` | 无 | 继续 unresolved | 无 | 无 recovered proposal |
| 61 | unresolved / `section_id=None` | 无 | 继续 unresolved | 无 | 无 recovered proposal |
| 62 | unresolved / `section_id=None` | `recovered:p0062:01` REJECTED | 继续 unresolved | 无 | 无 accepted structural anchor |
| 63 | unresolved / `section_id=None` | 无 | 继续 unresolved | 无 | 无 recovered proposal |
| 64 | unresolved / `section_id=None` | `recovered:p0064:01` AMBIGUOUS<br>`recovered:p0064:02` AMBIGUOUS<br>`recovered:p0064:03` REJECTED | 继续 unresolved | 无 | 无 accepted structural anchor |
| 65 | `observed_section_016` / 军民融合及产学研合作证明 | 无 | 保留 Native | 无 | Native section ownership remains authoritative |
| 66 | unresolved / `section_id=None` | `recovered:p0066:01` ACCEPTED_PROPOSAL<br>`recovered:p0066:02` REJECTED<br>`recovered:p0066:03` REJECTED | recovered_document_anchor | 无 | accepted composite visual title; only anchor, range unresolved |

## 未进入 Preview 的 proposal 与冲突

- 25 个 AMBIGUOUS、11 个 REJECTED 均保留为 E4C diagnostics，不转成 anchor。
- 本例没有 accepted proposal 与 Native ownership 冲突，没有同页两个 accepted proposal，也没有候选证据复用冲突；conflict 总数为 0。
- 对未来的冲突输入，preview 会记录 conflict 并保留 Native，不静默选择 recovered proposal。

## 行为界限

这是内部预览，不是正式 Native/Canonical 结构。没有为任何 recovered anchor 分配结束页、section_id 或业务章节层级；没有改变 Fallback、Provider、selected predictions、Canonical、Renderer 或 Audit。
