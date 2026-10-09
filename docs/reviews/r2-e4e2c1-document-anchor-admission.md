# R2-E4E2C1 Recovered Document Anchor Admission

本轮建立内部 admission gate，不接入正式 Pipeline。只读消费现有 E4B candidates、E4C proposals 和 E4D preview；不重新 OCR、识别标题、解析 PDF、调用 Provider 或计算 document range。

## 状态与准入

`pdffast/structure_reconciliation/anchor_admission.py` 输出 `DocumentAnchorAdmissionDecision`。`create_document_units(preview)` 仍可创建**明确标记 `anchor_status=PROPOSED`** 的 provisional recovered units，以保留 E4E1/E4E2B 的内部 characterization；传入 admission decisions 后，只有匹配 `ANCHOR_CONFIRMED` 决策的单位会升级状态。Native Primary 的状态为 `NOT_APPLICABLE`。未通过的 proposal 留在 E4D/decision 供审阅，不会冒充 confirmed anchor。该选择避免把 proposed 与 confirmed 藏在同一种无状态的 DocumentUnit 中。

第一版确认须同时满足：E4C `ACCEPTED_PROPOSAL`、`DOCUMENT_BOUNDARY_CANDIDATE`；E4D 有同页、同原始标题及 candidate refs 的无冲突 `RecoveredDocumentAnchor`，且无 Native ownership 或 proposal conflict；E4C 已将至少两条视觉标题行判为 `STRONG / adjacent_visual_title_lines`；原始 candidate refs 可追溯到同一 whole-page task 和 selected prediction，文字顺序一致，图像 bbox 在原顺序中相邻。admission 只校验 E4C 已形成的组及原始证据一致性，未重新寻找标题。单条高 confidence OCR 不能凭置信度过关。

确认只表示：**该候选逻辑文档与 `anchor_page` 的已确认标题锚点区域相交**。`bbox_coordinate_space=PROVIDER_INPUT_IMAGE`；保留 candidate、selected prediction 和 raw source refs，不把图像像素 bbox 伪装成 PDF 坐标，也不做坐标映射。它不确认整页所有权、页内其他区域、后续页、任何 record/section parent 或 `page_range=(N,N)`。

## case_003 只读 admission

从现有 `outputs/template_removal_review/case_003/` 的 Stage 3、Stage 6 与 selected predictions 重建 E4B/E4C/E4D。41 个 E4C proposals 中，以下 5 个通过 admission；其余不被提升。五组均为同一 whole-page prediction 的两条相邻 OCR visual title lines，保留原始阅读顺序，坐标系均为 `PROVIDER_INPUT_IMAGE`。

| Page | Proposal | Candidate refs（完整） | E4D conflict | Admission | Reason |
|---:|---|---|---|---|---|
| 27 | `recovered:p0027:01` | `p0027:s9_0027_page_fallback_0260f9ae5126:0007`<br>`p0027:s9_0027_page_fallback_0260f9ae5126:0008` | 无 | `ANCHOR_CONFIRMED` | “陕西省自然科学基础研究计划”＋“项目合同（任务）书”；两行同 task、同 selected prediction，bbox 顺序/间距成立 |
| 29 | `recovered:p0029:01` | `p0029:s9_0029_page_fallback_9ca6452f49a8:0009`<br>`p0029:s9_0029_page_fallback_9ca6452f49a8:0010` | 无 | `ANCHOR_CONFIRMED` | “陕西省教育厅服务地方专项计划项目”＋“合同书”；同一 whole-page prediction 的相邻复合标题 |
| 30 | `recovered:p0030:01` | `p0030:s9_0030_page_fallback_9ea797c3cdd5:0011`<br>`p0030:s9_0030_page_fallback_9ea797c3cdd5:0012` | 无 | `ANCHOR_CONFIRMED` | “陕西省自然科学基础研究计划项目”＋“结题审查结果的通知”；同 task、有序视觉标题组 |
| 36 | `recovered:p0036:01` | `p0036:s9_0036_page_fallback_e2a7405350fc:0014`<br>`p0036:s9_0036_page_fallback_e2a7405350fc:0015` | 无 | `ANCHOR_CONFIRMED` | “陕西省国际科技合作基地”＋“项目协议书”；同 task、有序视觉标题组 |
| 66 | `recovered:p0066:01` | `p0066:s9_0066_page_fallback_7fd06c196caf:0042`<br>`p0066:s9_0066_page_fallback_7fd06c196caf:0043` | 无 | `ANCHOR_CONFIRMED` | “科技成果登记表”＋“(基础理论、软科学类成果)”；同 task、有序视觉标题组 |

若未来的 accepted proposal 缺少第二条标题行、candidate refs 找不到、同页 Native ownership 冲突、标题与 E4D anchor 不一致、跨 task 混组、bbox 顺序或相邻关系不成立，gate 会返回 `NOT_ADMITTED`。这不是恢复 Provider 排名或修改 E4C/E4D 的判断。

## p29 与相邻边

p29 admission 成功后，可以确认 p29 **标题锚点区域**与该候选 DocumentUnit 相交。E4E2B 的 `29→30 = BOUNDARY` 是另一条独立证据：p30 有自己的 accepted document anchor。两者目前不会组合成 range。p29 的整页、其他 records、左/右页内边界仍未确认；`range_status=UNRESOLVED`、`page_range=None`。五个 recovered units 均如此，`section_parent_map={}`，没有 `record.document_id`。

本阶段不改变 Native、E4B/E4C/E4D、PageRelationDecision、Canonical、Renderer、Audit 或任何正式 output。下一阶段若要计算 coverage span，必须另行组合 admitted anchor intersection 与经核实的相邻页关系，不能从 anchor status 直接推导。
