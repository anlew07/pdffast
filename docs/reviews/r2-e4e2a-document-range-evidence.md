# R2-E4E2A Document Range Evidence Audit

本报告只读审计现有 `case_003` 产物和当前代码。没有重新运行 Provider，没有创建或修改 `DocumentUnit.page_range`、record ownership、Canonical 或正式输出。下文的 `SUPPORTED / UNSUPPORTED / AMBIGUOUS` 只评价**所列证据对某个边界或延续命题的支持程度**，不是已确认的 DocumentUnit 页归属。

## 数据来源与语义限制

- Native：`outputs/template_removal_review/case_003/01_stage1/page_profile.json`、`page_snapshot.jsonl`、`03_stage3/section_alignment.json`、`04_stage4/page_structure.json`、`05_stage5/result.json`、`06_stage6/normalized_text_flow.json`。
- Recovered：现有 `09_8_production_fallback/selected_prediction_index.json` 和 `selected_predictions/*.json`，经 E4B/E4C/E4D 的**只读**函数重建候选、proposal 和 document anchors。五个 `RecoveredDocumentAnchor` 在 p27、p29、p30、p36、p66。
- Stage 3 的 `section_id` 是 **Native section ownership**，不是 document ownership。E4E1 最初将 16 个 Native section ID 默认归入 Primary；E4E2B0 已撤销这一过早假设。当前这些 section 的 DocumentUnit parent 未确认。
- 下文的 p27 等数字是 PDF **物理页索引**。印在页面上的 `26/65` 等数字是源文件内容，不能与物理索引混为一谈。

## 当前真正可用的逐页信号

| 来源 | 实际字段或内容 | 对 document range 的限制 |
|---|---|---|
| Stage 1 profile / snapshot | `width`、`height`、`rotation`、`native_text`、`native_char_count`、`primary_type`、图片覆盖率、文字/图像/矢量和字体/词框 | 可比较页面形态；scan-like 页的 Native text 往往只有水印和整包页脚。尺寸相同不证明同一文档。 |
| Stage 3 / Stage 4 | Native observed heading、`section_id`、已确认的 Native section 页范围、逐页 blocks、block 类型、表格候选和阅读顺序状态 | Native heading 是结构边界证据，但“新 section”不必然等于“新 document”。 |
| Stage 5 / Stage 6 | 跨页表格 edge 的 `confirmed/unresolved`、逻辑 paragraph 的 `source_pages`、records、page index | 只有具体确认的跨页内容关系才可支持延续；不能把表格候选直接升级成文档关系。 |
| Selected prediction | `task_type`、`page_number`、text/confidence、`spatial_text`、`reading_blocks`、tables、`source_artifacts` 和 Provider 身份 | p27/29/30/36/66 的 RapidOCR 结果有 text 与 spatial boxes，**没有** reading blocks 或 tables；p34/35 的 MinerU 有 reading blocks/tables。Provider 名称与 task ID 仅供 provenance。 |
| E4B～E4D | 原始候选、E4C decision/role、已接受的 recovered document anchor、冲突与 Native ownership | Anchor 支持“此处可能有新文档边界”，不支持自动认领 anchor 页或后续页。AMBIGUOUS/REJECTED 不得提升。 |

当前**没有**统一、已验证的 `page_layout_fingerprint` 或跨 Provider 的 header/footer continuity 字段；只有上述可读取的原始特征。也没有一个通用的“Document Unit 内部页码”字段。

## Boundary evidence 与 continuity evidence

**Boundary：**新的 E4D document anchor、不同的 Native observed heading、文档标题/编号突变、独立封面或证书内容，以及与内容变化相互印证的尺寸/方向变化。单独的尺寸变化只能提示核查；扫描、旋转和裁边也会造成变化。

**Continuity：**可定位到**同一文档**的内部页码递增、稳定且具有区分力的文档编号/页眉、明确的跨页段落或已确认跨页表格、同一正文/表格内容的逐页延续。相同机构名称和类似版式需要与具体内容关系共同核验。

**不能用作 document continuity：**同一 Provider、相邻 task ID、同一 fallback route、同一 OCR confidence 区间、PDF 物理页相邻、没有新标题、全包重复的 `正式版` 水印，以及跨不同附件仍递增的 `n/65` 页脚。E3B Native 代码把后者称为 `pdf_page_number_consecutive`，但在这里它是**源内容中的整包连续页码**：p27 合同页为 `26/65`、p28 实验室通知为 `27/65`、p29 另一合同为 `28/65`、p30 另一项目通知为 `29/65`。它们显然不能因此成为同一 Document Unit。

### 内部页码、页眉页脚与版式核查

- p25 的 Native/OCR 可见“第 3 页”和 `24/65`；p26 是网页检索截图，OCR 可见 `1/1` 与 `25/65`。前者可能是来源表单内部页码，后者更像网页打印页数，不能把两者接成同一序列。
- p27～30 的 `26/65`～`29/65` 跨不同标题和项目编号递增，是整包页脚而非附件内部连续证据。p36～41 的类似序列也横跨协议书、证书和其他材料。p66 OCR 的 `45/85` 与前一页 `64/65` 不同，但 OCR/源件差异尚不能独立确定其文档起点。
- `正式版` 以拆字水印形式出现在多张不同附件页，E4C 还在 p41/p66 将它作为非结构候选拒绝。相同水印、机构名、徽标不应自动表明文档连续。
- Stage 1/4 有宽高、旋转、图片比例、block 分布；p29 为约 595×842、图片比例 0.37，p30 为约 596×842、比例 1.00，p31 切为横向约 842×595；p36 为 595×842、比例 0.32，p37 为横向 842×595、比例 1.00。它们是可用的辅助边界线索，但没有经过校准的文档版式指纹。RapidOCR `spatial_text` 的坐标属于 Provider 输入图像；不能未经坐标对齐就直接与 PDF Native bbox 比较。
- p34→35 内容都来自“科研管理系统”，OCR 表格行号显示延续；但 Stage 5 的 `cross_table_p0034...p0035...` edge **状态为 `unresolved`**，并非已确认表格跨页。这是值得进一步核查的 continuity candidate，不能充当已确认关系，更不能把 p36 的协议书并入其中。

## 五个 RecoveredDocumentAnchor 的邻页证据

| Anchor | 左侧与 anchor 的 boundary evidence | 向右的 boundary / continuity evidence | 判断：右侧延续 | 可安全给出的 range |
|---|---|---|---|---|
| **p27** 陕西省自然科学基础研究计划／项目合同（任务）书 | p26 是国家自然科学基金网页检索截图，p27 OCR 为项目编号 `2019JM-594` 的合同封面式内容；新 document boundary **SUPPORTED**。 | p28 有 Native observed heading“红外物理国家重点实验室”，正文是“开放课题批准通知”，Native `section_id=observed_section_015`，与 p27 合同不同。p27→28 的新结构边界 **SUPPORTED**；延续 **UNSUPPORTED**。 | **UNSUPPORTED** | **无**。不能因为 p28 是另一结构，就自动确认 p27 全页归属或 `page_range=(27,27)`。 |
| **p29** 陕西省教育厅服务地方专项计划项目／合同书 | p28 已有独立 Native observed heading；p29 OCR 为合同及编号 `19JC032`。p28→29 新边界 **SUPPORTED**。 | p30 又有已接受的 RecoveredDocumentAnchor，标题是“陕西省自然科学基础研究计划项目／结题审查结果的通知”，项目编号 `2017JM6061`，不同于 p29。p29→30 新边界 **SUPPORTED**；延续 **UNSUPPORTED**。 | **UNSUPPORTED** | **无**。p30 开始另一个候选文档，不等于 p29 的整页 membership 已证明；不能推出单页 range。 |
| **p30** 陕西省自然科学基础研究计划项目／结题审查结果的通知 | p29 的独立 anchor 与不同项目编号支持新边界：**SUPPORTED**。 | p31 切为横向扫描件，OCR 是“中国博士后科学基金资助证书”，另有资助编号 `2015T81044`；E4C 对 p31 标题仍判 `AMBIGUOUS`。p30→31 的内容/版式新边界线索 **SUPPORTED**，但尚无获准提升的 p31 document anchor；p30→31 延续 **UNSUPPORTED**。 | **UNSUPPORTED** | **无**。不能用 p31 的 ambiguous proposal 填补新单位，也不能推定 p30 单页归属。 |
| **p36** 陕西省国际科技合作基地／项目协议书 | p34/35 为科研管理系统页面及表格，p36 OCR 换为编号 `2017GHJD-007` 的协议书；p35→36 新边界 **SUPPORTED**。 | p37 横向扫描，是“陕西省创新人才推进计划”证书，编号 `2019SR2009`；p38/39 是不同获奖证书，p40 是另一证书，p41 又是德文 HZDR 材料。p36→37 延续 **UNSUPPORTED**；p37～41 各页的边界和归属仍需逐页确认。 | **UNSUPPORTED** | **无**。绝不能因为下一 accepted anchor 很远，就把 p37–41 延伸到 p36。 |
| **p66** 科技成果登记表／(基础理论、软科学类成果) | p65 Native observed heading 为“军民融合及产学研合作证明”；p66 为 image-dominant 的另一表单，E4D anchor 已接受。p65→66 新边界 **SUPPORTED**。 | p66 是 PDF 最后一页；EOF 是物理右边界，但没有下一页提供延续证据。OCR 的 `45/85` 不是已确认的内部页码。 | **AMBIGUOUS**（无右邻页可判） | **无**。EOF 不证明 p66 的全部 records 属于该单位，不能自动写 `(66,66)`。 |

状态中的 `UNSUPPORTED` 表示现有证据**不支持把右邻页并入该 anchor 单位**，不表示已完成该单位的左/右范围证明。五个 recovered units 继续保持 `range_status=UNRESOLVED`、`page_range=None`。

### 邻域检查补充

- **p25–32：**p25 有源表单页码，p26 为网页检索，p27 合同，p28 Native 通知，p29 合同，p30 结题通知，p31 证书，p32 网页/矢量内容。这段连续的物理页包含多种来源，不能用统一页脚或“未识别新标题”串成一份文档。
- **p34–41：**p34/35 同为科研管理系统，提供待核查的内容延续；p36 协议书后 p37–40 连续出现各自不同的证书内容，p41 为德文材料。当前 E4C 对 p38/p39 的候选分别为 `AMBIGUOUS`，未产生可以替代 p36 的已接受锚点。
- **p64–66：**p64 OCR 有“中国科学院上海微系统与信息技术研究所／应用证明”两个 `AMBIGUOUS` 候选，p65 有 Native observed heading，p66 有新的 accepted document anchor。p64/p65 的边界尚不能借 p66 反推；p66 的右边界仅是 EOF。

## Primary DocumentUnit 与页归属

Stage 3 的 16 个 Native sections 各有可靠的**section**页归属，合计 22 个物理页，分布为 `2–20`、`24`、`28`、`65`。这些信息不证明它们属于 Primary DocumentUnit。E4E2B0 修正后，Primary 的 `section_ids=()`，`section_parent_map={}`；所有 Native section 的 document parent 暂时未知。尤其 p28、p65 的 Native heading 位于附件样内容邻域。未来可以从“已确认 section parent + 已确认 section 页 ownership”推导 document page ownership，但必须先独立核实 section 的 document parent。

## 状态与连续 range 的建议

- 在概念上建议保留 `UNRESOLVED / PARTIAL / CONFIRMED`：只有确认**至少一个属于该 unit 的页面**且外延仍未知，才是 `PARTIAL`。Anchor 已知、range 未知仍为 `UNRESOLVED`；“可能属于”也不应转成 `PARTIAL`。`PROBABLE` 更适合逐页诊断，不宜直接作为可消费的所有权状态。相互矛盾的证据记录为 `CONFLICT`，而不是默选一个 unit。
- 对当前目标，DocumentUnit 的已确认页范围宜以**连续物理页区间**作为正常不变量。若只有已确认前缀、后续未定，应表达为 partial continuous span + unknown extent；不要把零散页硬塞进一个 `[start,end]`。遇到真正非连续或交错文档时保留冲突/人工核验，不为极端样本预先开放任意 page set。
- 当前五个 recovered units **没有一个**可安全自动写出 `page_range`，即使 p29 与 p30 连续出现两个 anchor，或 p66 位于 EOF。Native section 的 22 页可继续维持原本的 section ownership；Primary document range 也未因此确认。

## E4E2B 的最小输入与输出建议（本轮不实现）

输入仅取：物理页序、Native section anchor/ownership、E4D document anchors 与冲突、逐页 Native/OCR **内容及原始证据引用**、可信度、页尺寸/方向、明确可核验的内部页码或文档编号、已确认的跨页正文/表格关系。Provider 身份/task routing 只随证据保留 provenance，不参与结构判断。

先逐相邻页输出 `boundary / continuity / insufficient / conflict` 及可追溯理由，区分整包页脚、水印和文档内部标识。只有在锚点页 membership 与每条相邻延续边都有足够独立证据、且没有 competing anchor/Native boundary 时，后续阶段才考虑连续 range；否则保持 unresolved。E4E2B 不应从“直到下一个 anchor”或“直到 EOF”生成 range，也不应写 `record.document_id`。
