# R2-E4E2C0 Anchor Membership / Document Range Semantics

本轮只明确内部契约，不求解 recovered document range，不改 `DocumentUnit` 字段、E4D / E4E2B 判断器、Pipeline 或正式输出。下面的“确认”指当前数据链可以支持的事实，不等于未来 resolver 已经执行。

后续 E4E2C1 已新增独立 anchor admission：通过后可以确认**标题锚点区域交集**，但仍不确认整页或完整 `page_range`。本报告下文的“当前尚不能确认交集”描述的是 E4E2C0 尚未有 admission gate 时的基线。

后续 E4E2C coverage resolver 已在 admitted anchor seed 的基础上引入 `PARTIAL / RESOLVED`，并将 `page_range` 定义为已确认的连续页面交集跨度。下文对 `CONFIRMED` 及“不需要 PARTIAL”的讨论仅记录 E4E2C0 当时的状态，不代表当前内部契约。

## 四种不能混同的事实

| 命题 | 当前 accepted recovered anchor 能否确认 | 解释 |
|---|---|---|
| A. Document title / anchor evidence 出现在物理页 N | **能** | E4B candidate refs 经 E4C 接受，并由 E4D 保留为 `RecoveredDocumentAnchor`；`DocumentUnit.anchor_page` 记录该证据的位置。确认的是证据位置和提案身份。 |
| B. 该候选 DocumentUnit 确实覆盖页 N 的某个区域 | **尚不能作为 confirmed membership** | E4D 将其称作可能的 document boundary，未独立确认候选文档身份、标题区域与文档内容的归属。Anchor 支持交集假设，但现有对象没有 confirmed intersection 字段。 |
| C. 整个物理页 N 独占属于该 DocumentUnit | **不能** | 一页可能有多个逻辑文档，标题可能只占一个区域。 |
| D. 页 N 上某些 records 属于该 DocumentUnit | **不能** | 需要针对具体 record 的独立证据；当前不写 `record.document_id`。 |

因此 `anchor_page=29` 是**证据定位**，不是已确认的 page membership。E4E2B 的 `BOUNDARY` 也是相邻页关系判断，不将 A 升级为 B/C/D。现有 `anchor_page`、`evidence_refs`、`range_status=UNRESOLVED`、`page_range=None` 已能表达当前事实；本轮无需增加 `anchor_membership` 状态。未来若有经核实的文档交集证据，可再单独表达 confirmed intersection，不能复用 `anchor_page` 偷换语义。

## `page_range` 的长期语义

推荐将 `DocumentUnit.page_range=(start,end)` 定义为**连续物理页覆盖跨度**：该逻辑文档与跨度内每页至少一个区域相交，且左右端点均已由可追溯证据确定。它是 document coverage / intersection span，**不是**这些页的独占所有权，也不规定页内分界线。仅有 title anchor、某条相邻边的 `BOUNDARY`、或 PDF 的 EOF，均不足以确认一个完整 span。

两个已确认跨度可以重叠，例如 A=`29–30`、B=`30–31`，若 p30 上确实发生页内文档转换。当前 `DocumentUnit` 只校验每个跨度的端点，没有全局“不重叠”约束；这符合推荐语义。未来 resolver 可以因证据不足暂不产出重叠跨度，但那只是**实现能力限制**，不是语义不变量。单个 tuple 只能描述连续 span；对于非连续覆盖，不能用包含空隙的大区间假装每页都相交，应保持未解或另行设计表达。

当前代码状态名为 `UNRESOLVED` / `CONFIRMED`，不是 `RESOLVED`。`CONFIRMED` 在 dataclass 中仅校验 `page_range` 端点合法，**不自动验证证据充分性**；未来 resolver 必须承担证据校验。现有 case_003 全部仍为 `UNRESOLVED / None`。

### `PARTIAL` 暂不引入

E4E2A 提过 `PARTIAL`。现在只有 anchor evidence 所在页及 edge decisions，没有已确认的 DocumentUnit page intersection，也没有已确认的左右外延。此时增加 `PARTIAL` 会让“候选 anchor”被误读为“已确认部分覆盖”。保持 `UNRESOLVED`。将来若确实确认了某些页面与单位相交、但至少一侧 extent 未知，再考虑明确的 partial coverage 表达；不得把 `page_range=(N,N)` 用作“只确认一个点”的临时状态。

## Coverage 与 ownership

即使未来 `page_range=29–31` 达到 `CONFIRMED`，也只说明该文档与 p29、p30、p31 有交集。它不会把这三页的全部 records 写成同一个 `document_id`。同页的其他文档、公共页眉、包级水印或未解区域可与该跨度共存。`record.document_id` 需要按 record 的文本、区域、表格与 provenance 单独判定。

Native Section 的页归属也不等于 DocumentUnit parent。case_003 的 16 个 Native sections 分布于 `2–20`、`24`、`28`、`65`，当前 `Primary.section_ids=()`、`section_parent_map={}`。若未来**独立确认**某个 Section 属于某 DocumentUnit，其已确认的 Native 页覆盖可以成为该单位的**交集**证据；既不能反向从 Native section 推定 Primary parent，也不能由 section 的页覆盖直接推定整页 records 归属。

## case_003 现有事实

以下左/右 edge 是 E4E2B 的判断，不是对应 DocumentUnit 的完整左右边界。`BOUNDARY` 表示相邻页关系有强边界证据；它不确认 anchor 页全页归属，也不自行求解该单位跨度。

| Recovered unit | Anchor evidence 页 | 左 edge | 右 edge | 已确认的交集 / 完整 range | 全页 / record ownership |
|---|---:|---|---|---|---|
| p27 合同书 | 27 | 26→27 `BOUNDARY` | 27→28 `INSUFFICIENT` | 无 / `UNRESOLVED` | 无 |
| p29 教育厅合同书 | 29 | 28→29 `BOUNDARY` | 29→30 `BOUNDARY` | 无 / `UNRESOLVED` | 无 |
| p30 结题通知 | 30 | 29→30 `BOUNDARY` | 30→31 `INSUFFICIENT` | 无 / `UNRESOLVED` | 无 |
| p36 项目协议书 | 36 | 35→36 `BOUNDARY` | 36→37 `INSUFFICIENT` | 无 / `UNRESOLVED` | 无 |
| p66 科技成果登记表 | 66 | 65→66 `BOUNDARY` | EOF，不存在 p67 edge | 无 / `UNRESOLVED` | 无 |

**p29 具体结论：**可以确认 E4D 接受的标题锚点证据位于 p29，且 `29→30` 的 edge 因 p30 有独立 accepted document anchor 而判 `BOUNDARY`。仍不能确认 p29 全页由 p29 DocumentUnit 独占、p29 的所有 records 属于它、或其完整 `page_range=(29,29)`。左 edge `28→29 = BOUNDARY` 也没有解决 p29 页内边界与候选 document identity 的独立验证。

## E4E2C resolver 的安全前置条件

下一阶段可以先寻找并记录**某个 DocumentUnit 与某页相交的独立证据**，再核查每条外延 continuity、与相邻候选的冲突及左右终止证据。只有完整连续覆盖证据成立，才可设置 `CONFIRMED` span；若只有 anchor/edge，应保持 `UNRESOLVED`。页内 record ownership 与 section parent 仍是独立决策，不能由 span 传播赋值。重叠跨度应允许表达；非连续覆盖需显式保留未解状态，不得用大区间掩盖空隙。
