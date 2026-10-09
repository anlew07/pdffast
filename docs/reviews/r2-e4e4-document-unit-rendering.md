# R2-E4E4 DocumentUnit Renderer

## 呈现契约

Renderer 只读取 Canonical 1.1 的 `document_units`，不重算锚点、coverage 或 Provider 结果。已有 Section 仍按原规则渲染成 `# 章节标题`；DocumentUnit 使用独立的元数据块：

```text
<!-- pdffast-document-unit: <document_id>; anchor-page: <page> -->
【PDFFast文档边界元数据｜锚点第<page>页｜页内具体边界未确定｜<coverage>】
标题原文 1：<title_parts[0]>
标题原文 2：<title_parts[1]>
【PDFFast文档边界结束】
```

`title_parts` 按 Canonical 原顺序逐行展示，不合成新标题；`UNKNOWN` role 和内部 evidence refs 不进入 Markdown。HTML 注释保留 unit identity，括号标记明确这是 PDFFast 元数据，不是 PDF 原文或 Section heading。

`PARTIAL` 写作“已确认覆盖：起–止页；完整范围未确定”。`RESOLVED` 写作“当前证据确认覆盖：起–止页（非独占）”。两者都不宣称整页或 records 归属。Canonical 目前没有页内边界坐标，也没有左右 extent 字段，因此不猜测页内精确分界及未知方向。

Renderer 优先在该页整页 fallback 的已渲染内容中找到 `title_parts[0]` 的首次精确出现，将元数据块放在该原文标题行之前；找不到时放在该页首次内容之前。Native paragraph 即使恰好与标题同名，也不被当作 recovered anchor。同一页的多个单位分别输出，保持 Canonical 顺序。Section heading 的生成规则与层级不变。

## case_003 人工对照

新文件：[case_003 document.md](../../outputs/document_unit_render_review/case_003/document.md)。以下“前文 → 标题”表示旧 Markdown 的相邻原文；新 Markdown 只在箭头处插入上述元数据块，然后接回原文标题。

| 页 | 旧 Markdown 的前文 → 标题 | 新增块的标题原文 | coverage |
|---|---|---|---|
| 27 | `项目编号：2019JM-594` → `陕西省自然科学基础研究计划` | `陕西省自然科学基础研究计划` / `项目合同（任务）书` | PARTIAL，27–27 |
| 29 | `【整页识别开始｜第29页】` → `陕西省教育厅服务地方专项计划项目` | `陕西省教育厅服务地方专项计划项目` / `合同书` | RESOLVED，29–29 |
| 30 | `【整页识别开始｜第30页】` → `陕西省自然科学基础研究计划项目` | `陕西省自然科学基础研究计划项目` / `结题审查结果的通知` | PARTIAL，30–30 |
| 36 | `项目类型：国际科技合作基地` → `陕西省国际科技合作基地` | `陕西省国际科技合作基地` / `项目协议书` | PARTIAL，36–36 |
| 66 | `有效期至：2016年12月` → `科技成果登记表` | `科技成果登记表` / `(基础理论、软科学类成果)` | RESOLVED，66–66 |

## case_004 人工对照

新文件：[case_004 document.md](../../outputs/document_unit_render_review/case_004/document.md)。这两页在锚点前已有其他正文，因此元数据块位于观察到的标题行前，而非整页 OCR 块前。

| 页 | 旧 Markdown 的前文 → 标题 | 新增块的标题原文 | coverage |
|---|---|---|---|
| 83 | `和增韧补强方法研究,2020.` → `陕西高等学校科学技术奖` | `陕西高等学校科学技术奖` / `获奖证书` | PARTIAL，83–83 |
| 108 | `5.2陕西省地方标准：《既有基坑工程鉴定与加固技术规程》，2020年5月。` → `陕西省建筑科学研究院有限公司` | `陕西省建筑科学研究院有限公司` / `关于陕西省地标《既有基坑工程鉴定与加固` / `技术规程》编制工作的邀请函` | PARTIAL，108–108 |

## 保持项与限制

case_003 的 5 个、case_004 的 2 个元数据块移除后，新 Markdown 与各自旧 `result/document.md` **逐字节相同**。这同时核对了正文字符及顺序、表格、图像引用和 fallback 内容。Canonical 的 sections、pages、records、fallback_overlays 与旧结果相同；Renderer 不修改传入的 Canonical dict。历史样本文件未覆盖，未重跑 Provider。Audit 语义未修改。

标题行定位只是呈现位置，不构成 record ownership 或页内精确边界证据。若同页有重复标题，Renderer 取首次匹配；这类复杂页仍需人工检查。完整语义 Audit 留待下一阶段。
