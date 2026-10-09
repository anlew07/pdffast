# R2-E4E2C Document Coverage Resolution

本轮仅在 `pdffast/structure_reconciliation/coverage.py` 生成内部 coverage 结果。输入是已建立的 `DocumentUnit` 和 E4E2B `PageRelationDecision`；只有 `anchor_status=ANCHOR_CONFIRMED` 的 recovered unit 才以 anchor 页为已确认交集 seed。`PROPOSED` 不形成 coverage。输出为新的冻结 `DocumentUnit` 与左右 extent、停止原因、使用过的 edge evidence refs；不修改输入或正式 Pipeline 输出。

## 状态与跨度语义

`range_status` 现在采用 `UNRESOLVED / PARTIAL / RESOLVED`：

- `UNRESOLVED`：没有 admitted anchor seed；`page_range=None`。
- `PARTIAL`：至少有一个已确认页面交集，`page_range` 是**目前已确认的连续 coverage span**，但至少一个方向遇到 `INSUFFICIENT`、`CONFLICT` 或缺失 edge，完整 extent 未知。
- `RESOLVED`：已确认 span 的左右两侧均由 `BOUNDARY` 或物理 `BOF / EOF` 关闭；此时 `page_range` 是完整已确认 coverage span。

`page_range` 表示逻辑文档与物理页的交集，不表示整页独占。不同 DocumentUnit 的 span 长期允许在同一物理页重叠。它不推导 `record.document_id` 或 section parent。

从 anchor 向两侧逐 edge 传播：`CONTINUITY` 加入相邻页并继续；`BOUNDARY` 关闭该侧；`INSUFFICIENT` 停止并保持 `OPEN`；`CONFLICT` 停止并保留证据 refs。不得越过未知或冲突边。只有传播到第 1 页/最后一页时，BOF/EOF 才关闭对应侧；物理边界本身不创建 seed。相同输入的结果稳定，不依赖时间或 Provider 执行顺序。

## case_003 只读 characterization

使用现有 Stage 3、Stage 6、selected predictions 重建 E4B/E4C/E4D、C1 admission 和 E4E2B page relations；没有运行 Provider。65 条 edge 仍为 0 CONTINUITY、5 BOUNDARY、60 INSUFFICIENT、0 CONFLICT。

| DocumentUnit | Anchor 页 | 左 edge / closure | 右 edge / closure | Confirmed span | 状态 | 停止原因 |
|---|---:|---|---|---|---|---|
| recovered p27 | 27 | 26→27 `BOUNDARY` / `CLOSED` | 27→28 `INSUFFICIENT` / `OPEN` | 27–27 | `PARTIAL` | 右侧证据不足 |
| recovered p29 | 29 | 28→29 `BOUNDARY` / `CLOSED` | 29→30 `BOUNDARY` / `CLOSED` | 29–29 | `RESOLVED` | 两侧边界关闭 |
| recovered p30 | 30 | 29→30 `BOUNDARY` / `CLOSED` | 30→31 `INSUFFICIENT` / `OPEN` | 30–30 | `PARTIAL` | 右侧证据不足 |
| recovered p36 | 36 | 35→36 `BOUNDARY` / `CLOSED` | 36→37 `INSUFFICIENT` / `OPEN` | 36–36 | `PARTIAL` | 右侧证据不足，不越过 36→37 |
| recovered p66 | 66 | 65→66 `BOUNDARY` / `CLOSED` | EOF / `CLOSED` | 66–66 | `RESOLVED` | 物理末页关闭右侧；没有伪造 p67 |

每条已检查 edge 的 `evidence_refs` 保存在内部 resolution 结果中。Primary 未取得 admitted recovered anchor，仍为 `UNRESOLVED / None`，`section_ids=()`。五个 recovered units 的 `section_ids` 也保持空；`section_parent_map={}`。

尤其 p29 的 `RESOLVED (29,29)` **只确认该候选文档在 p29 有标题锚点区域交集、且按当前边证据不向相邻物理页延续**。p29 可能还有其他文档的区域、公共页眉或未解内容；不能把 p29 全部 records 自动赋予此 DocumentUnit。p66 的 EOF 同样不证明整页独占。

证据限制：当前 E4E2B 可因右页出现新的 document anchor 而给出 `BOUNDARY`。如果后来确认旧文档也与该右页相交（页内转换），需要重新评估该 edge 的非延续含义；本轮的 `RESOLVED` 是**相对于当前 edge decisions** 的结果，不能当作不可修订的真实文档边界。

本轮没有修改 Native、E4B/E4C/E4D、Anchor Admission、PageRelation、Fallback、Provider、selected predictions、Canonical、Renderer、Audit 或正式 outputs。没有写 `record.document_id`，没有建立 section parent；后续 record/section 归属需要独立证据与阶段。
