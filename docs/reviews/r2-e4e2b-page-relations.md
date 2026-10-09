# R2-E4E2B Adjacent Page Relationship Decision

本轮只产生内部 `PageRelationDecision`，没有生成 `DocumentUnit.page_range`，没有分配 record 或 section 的 document parent，也没有写 Pipeline / Canonical / Renderer / Audit。读取的是现有 case_003 Stage 3、Stage 6 和 selected predictions；通过 E4B/E4C/E4D 的只读函数重建 accepted anchors，没有运行 PDF 解析、OCR 或 Provider。

## 判定规则

`pdffast/structure_reconciliation/page_relations.py` 对每条真实相邻物理页边分别给出四种结果：

- `BOUNDARY`：右页存在 E4D 已接受的 `RecoveredDocumentAnchor`，或另有带来源引用的已核实独立文档起点、不同文档标识、内部页码重新开始证据。
- `CONTINUITY`：存在已核实的文档内部页码连续、相同且有区分力的文档标识、确认的跨页内容，或确认只属于局部文档的页眉页脚。没有发现新标题不是正向证据。
- `CONFLICT`：同一边同时有上述强 continuity 与强 boundary 证据；不以分数静默选择。
- `INSUFFICIENT`：没有足够的强证据。新 Native observed heading 会作为可追溯的**弱边界线索**记录，但不自动表示新 DocumentUnit。

`SAME_PROVIDER`、连续 task ID、相同 fallback route、类似 OCR confidence、包级 `n/65` 页码、公共“正式版”水印、物理页相邻、没有 heading、单独的版式相似都不能成为 continuity。外部 `CONFIRMED` / `VERIFIED` 证据须先核实其文档作用域并附 source refs；本轮没有把 case_003 的 OCR 文本差异或包级页码提升成这类证据。

E4D anchor 只支持相邻边界判断，**不确认锚点整页的 records 属于该 DocumentUnit**。即使 `29→30 = BOUNDARY`，也不能推出 p29 单页 range。EOF 不是第 67 页。

## case_003 指定边

表内 `selected` 表示现有 selected prediction 文件中的可见内容，属于人工审计上下文；若未列为强证据，不影响自动 decision。`pNN` 均为物理页。锚点证据在对象中保留 `anchor_id`、`proposal_id`、candidate refs；Native heading 保留原 section ID。

| Left | Right | Continuity evidence | Boundary evidence / 审计上下文 | Decision | Reason |
|---:|---:|---|---|---|---|
| 26 | 27 | 无；包级页码不计 | p27 accepted document anchor（项目合同书；`recovered:p0027:01`）；p26 selected 是基金检索网页 | **BOUNDARY** | 右页有 accepted document anchor；不推定 p27 全页归属 |
| 27 | 28 | 无；`26/65→27/65` 是包级页码 | p28 Native `observed_section_015`，标题“红外物理国家重点实验室”；Native 正文是“开放课题批准通知”，与 p27 合同内容不同，但 Native heading 不等于已核实的新 DocumentUnit 起点 | **INSUFFICIENT** | 记录 heading 边界线索；尚缺独立的 document-start 验证 |
| 28 | 29 | 无 | p29 accepted document anchor（教育厅合同书；`recovered:p0029:01`） | **BOUNDARY** | 右页有 accepted document anchor |
| 29 | 30 | 无；连续包级页码不计 | p29 与 p30 各有独立 accepted document anchor；p30 为另一项目“结题审查结果的通知”（`recovered:p0030:01`） | **BOUNDARY** | p30 的独立 accepted anchor 是强边界；不推出 p29 range `[29]` |
| 30 | 31 | 无 | p31 selected 是中国博士后科学基金资助证书（`s9_0031_page_fallback_a62a1443f09e`）；E4C 候选尚为 ambiguous，没有 accepted anchor | **INSUFFICIENT** | 文档内容差异待独立核实，不能把 ambiguous proposal 提升为边界 |
| 35 | 36 | 无；Stage 5 的 p34→35 表格 edge 仍是 unresolved，不能外推 | p36 accepted document anchor（国际科技合作基地项目协议书；`recovered:p0036:01`） | **BOUNDARY** | 右页有 accepted document anchor |
| 36 | 37 | 无；`35/65→36/65` 是包级页码 | p36 selected 协议书编号 `2017GHJD-007`；p37 selected 是证书 `2019SR2009`（`s9_0037_page_fallback_6dbaf5fed037`），版式方向也变化；这些差异尚未核实为独立 document-start / identifier 证据 | **INSUFFICIENT** | 证书内容提示人工核查，但不能仅凭 OCR 文本和版式自动定边界 |
| 37 | 38 | 无 | p37 与 p38 selected 分别为不同证书；p38 E4C 未产生 accepted document anchor | **INSUFFICIENT** | OCR 内容差异尚未提升为核实的文档标识 |
| 38 | 39 | 无；同为证书不是同一文档证据 | p38 / p39 selected 的证书项目和编号不同；p39 E4C 未产生 accepted anchor | **INSUFFICIENT** | 两边均缺经核实的文档边界或延续关系 |
| 39 | 40 | 无 | p40 selected 为另一奖项证书（`s9_0040_page_fallback_57df73534166`） | **INSUFFICIENT** | 独立内容线索仍未达到 confirmed boundary 标准 |
| 40 | 41 | 无 | p41 selected 为德文 HZDR 材料（`s9_0041_page_fallback_4f9e4f69de66`）；语言与内容变化明显 | **INSUFFICIENT** | 需独立确认新文档起点；不同语言本身不是自动归属规则 |
| 64 | 65 | 无 | p65 Native `observed_section_016`，标题“军民融合及产学研合作证明”；p64 selected 为中科院上海微系统所“应用证明” | **INSUFFICIENT** | Native heading 是边界线索，不自动表示新的 DocumentUnit |
| 65 | 66 | 无 | p66 accepted document anchor（科技成果登记表；`recovered:p0066:01`） | **BOUNDARY** | 右页有 accepted document anchor |
| 66 | EOF | 不适用 | 文件结束；不存在 p67 | **无 edge decision** | EOF 不确认 p66 全页 membership 或单页 range |

全 66 页形成 **65** 条真实相邻边：`CONTINUITY=0`、`BOUNDARY=5`、`INSUFFICIENT=60`、`CONFLICT=0`。`CONTINUITY=0` 表示当前输入没有已核实的文档延续证据，并不表示 PDF 不存在跨页文档。单元测试分别覆盖已确认内部页码产生 CONTINUITY，以及强 continuity 与 boundary 同时存在时产生 CONFLICT。

## 所有权与产物保护

case_003 仍有 1 个 Primary 和 p27/p29/p30/p36/p66 五个 recovered `DocumentUnit`；全部 `range_status=UNRESOLVED`、`page_range=None`。16 个 Native sections 仍存在，`Primary.section_ids=()`、`section_parent_map={}`。没有 `record.document_id` 写入。正式 `outputs/template_removal_review/` 文件、Canonical 和 Markdown 均未重建。
