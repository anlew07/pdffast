# R2-E4E1 Document Unit Contract

本轮只建立内部结构契约。它消费 E4D `ReconciledStructurePreview`，不接入 Pipeline、Canonical、Renderer、Audit 或 `ParseResult`，不写任何 Stage/result artifact。

## 对象与语义

实现位于 `pdffast/structure_reconciliation/document_units.py`。

| 字段 | 含义 |
|---|---|
| `document_id` | 在同一 PDF package 中稳定的内部单位身份；不使用标题作为唯一键。 |
| `role` | 中性结构角色：`PRIMARY`、`ATTACHED`、`UNKNOWN`。本轮只创建 `PRIMARY` 和 `UNKNOWN`；不会凭标题猜业务类别或附件身份。 |
| `source` | 建立单位的结构证据来源：`NATIVE` 或 `RECOVERED`，与角色分开。Provider 名称不作为 document 类型。 |
| `anchor_ref`, `anchor_page` | 原始 E4D document anchor 的身份与所在页。Primary Native 容器目前没有可靠的单一 anchor。 |
| `title_parts`, `evidence_refs` | 原始 recovered 标题片段和 candidate refs；不合成业务标题。 |
| `range_status`, `page_range` | 范围是否确认及可选页范围；本轮创建的单位全是 `UNRESOLVED` / `None`。 |
| `section_ids` | 已有独立证据确认属于该单位的 Section ID；允许为空，不修改原 Section schema。 |
| `anchor_status` | E4E2C1 起，Native 为 `NOT_APPLICABLE`；recovered 单位由 E4D preview 构造时为 `PROPOSED`，通过独立 admission gate 后可为 `ANCHOR_CONFIRMED`。此状态只确认标题锚点区域交集，不确认页范围或整页归属。 |

对象刻意没有 `record_ids`、`document_id` 写回字段或 Provider 运行数据。`section_parent_map(units)` 从已确认的 `section_ids` 导出父映射并拒绝重复父归属或重复 document ID。Section 可以没有已确认的父 Document Unit；有父单位时最多只能属于一个。Document Unit 也可以没有 Section。Primary 是一个尚无确认 section parent、page range 或 record ownership 的内部单位。此前将全部 Native sections 放入 Primary，是过早的 characterization assumption，现已取消。

## ID 与边界不变量

- Primary ID 为 `document:native:primary`，作用域是一份 PDF package。
- Recovered ID 由 anchor 页和 `SHA-256(page, E4D anchor_id, candidate_refs)` 的前 12 位构成；同一输入重复计算结果相同。相同标题出现在不同页时具有不同身份。
- 只有 E4D `RecoveredDocumentAnchor` 可生成 recovered `DocumentUnit`。`RecoveredSectionAnchor` 不会生成单位；E4C `AMBIGUOUS` / `REJECTED` 未进入 E4D anchor，因此也不会生成单位。
- Recovered 单位使用 `role=UNKNOWN`：E4D 的 document boundary 建议并未独立证明它属于主文档还是附件。
- `anchor_page=29` 与 `page_range=None` 可以同时成立。Anchor 页不自动成为已确认文档页，后续页更不会按下一个 anchor 划分。
- E4E2C1 的 `create_document_units(preview)` 保留 provisional recovered units 并显式标记 `PROPOSED`；只有提供匹配的 confirmed admission decision 才标记 `ANCHOR_CONFIRMED`。确认后仅承认标题证据区域与候选 DocumentUnit 的交集，仍不确认整页 membership。
- 本轮不分配 Content Record 的 `document_id`。没有 recovered document range，就无法证明某个 record 属于哪个 recovered 单位；Native record 和正式 Canonical 保持原样。

## case_003 只读 characterization

从现有 `outputs/template_removal_review/case_003/03_stage3/section_alignment.json`、Stage 6 flow 和 selected predictions 重建 E4B/E4C/E4D 预览；**没有调用 Provider**。内部得到 6 个单位：

| 单位 | source / role | anchor 页 | 原始 title parts | sections | range |
|---|---|---:|---|---:|---|
| `document:native:primary` | NATIVE / PRIMARY | 无 | 无 | 0 | UNRESOLVED / None |
| recovered p27 | RECOVERED / UNKNOWN | 27 | 陕西省自然科学基础研究计划；项目合同（任务）书 | 0 | UNRESOLVED / None |
| recovered p29 | RECOVERED / UNKNOWN | 29 | 陕西省教育厅服务地方专项计划项目；合同书 | 0 | UNRESOLVED / None |
| recovered p30 | RECOVERED / UNKNOWN | 30 | 陕西省自然科学基础研究计划项目；结题审查结果的通知 | 0 | UNRESOLVED / None |
| recovered p36 | RECOVERED / UNKNOWN | 36 | 陕西省国际科技合作基地；项目协议书 | 0 | UNRESOLVED / None |
| recovered p66 | RECOVERED / UNKNOWN | 66 | 科技成果登记表；(基础理论、软科学类成果) | 0 | UNRESOLVED / None |

p29 的内部 ID 是 `document:recovered:p0029:284ce4af2cff`；它保留 E4D anchor ref 与两个 candidate refs，但没有 Section、record ownership 或页范围。五个 recovered units 都是 document units，不是 recovered sections。

Stage 3 仍有 16 个 Native section ID；它们的 DocumentUnit parent 尚未由 document segmentation / range evidence 确认。此时 `section_parent_map` 为空，不得把 Native section 的存在解释为 Primary membership。

## case_004 旧产物与当前工作树

`outputs/template_removal_review/case_004/result/document.json` 是 E3A/E3B 之前的旧 Canonical artifact；其所依据的旧 Stage 3 unresolved 区间为 `1`、`21–114`，不能代表当前 Native 工作树。本轮对现有 Stage 1 快照调用当前 `discover_sections` 的只读计算得到：15 个 Native sections，新增锚点页 `25 / 48 / 80 / 90 / 101`，第 101 页章节延续到 114，unresolved 区间为 `1`、`21–24`。没有重跑 Pipeline、Provider，也没有重建 Canonical。

## 后续边界

正式接入前仍需单独决定 recovered anchor 的准入证据、文档范围、Section 重新归属和 record ownership。本轮的单位列表不得被解释为最终 `document.json` 树，也不得用它改变 Markdown 标题或 Audit 结论。
