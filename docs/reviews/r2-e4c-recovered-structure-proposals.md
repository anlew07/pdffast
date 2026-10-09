# R2-E4C case_003 recovered structure proposals

使用已有 E4B 的 46 个候选和 Native page ownership 做只读裁决。没有重新解析 Provider 输出、重新提取候选或计算章节页范围；`ACCEPTED_PROPOSAL` 也不是正式 Section。

- Candidate：46；proposal：41。
- Proposal 决策：ACCEPTED_PROPOSAL=5，AMBIGUOUS=25，REJECTED=11。
- Candidate 归属：accepted=10，ambiguous=25，rejected=11。两个 candidate 可以属于同一个 proposal。
- `structure_strength` 是结构证据级别，不是 Provider OCR confidence；本轮没有把它写进 Canonical。

## 重点结果

- p29：`陕西省教育厅服务地方专项计划项目` + `合同书` 按原始顺序组成 `recovered:p0029:01`。两行属于同一整页 task，在输入图像坐标系中相邻、居中、水平排布，故为 `ACCEPTED_PROPOSAL / DOCUMENT_BOUNDARY_CANDIDATE`；p29 Native ownership 仍 unresolved。
- p22、p41、p64、p66 的“正式版”：短文本跨四页重复，并呈现极大的相对行高和装饰性位置，均为 `REJECTED / repeated_page_decoration`。规则不含这个字面量。
- p26 的 `ISIS`、`单位名称`、`跳转至`：密集 OCR 页面中的短且不够突出的字段或界面碎片，均为 `REJECTED / short_field_or_interface_fragment`。
- p34/p35：E4B 没有 heading candidate，本轮没有凭阅读块或正文重新提取。
- p43/p44/p49/p51：论文标题及页内小标题全为 `AMBIGUOUS`；Provider 的 Markdown heading 仅作证据，不能决定 PDFFast 顶层章节。
- p59：两个 Markdown heading 也是 `AMBIGUOUS`，其中“会议日程：”建议角色为 `LOCAL_HEADING`。
- 参考项目曾把整句正文误标为 heading。本轮通用的长句、逗号及句末句号组合可拒绝这类 Provider heading；该历史实例属于 REGION task，不在本次 46 个候选里。

## 逐页候选裁决

| Page | Native ownership | Candidate text | Evidence | Decision | Proposal / grouping | Suggested role | Reason |
|---:|---|---|---|---|---|---|---|
| 21 | unresolved | 国家自然科学基金资助项目批准通知 | `OCR_VISUAL_LINE` | `AMBIGUOUS` | `recovered:p0021:01` (1): 国家自然科学基金资助项目批准通知 | `DOCUMENT_BOUNDARY_CANDIDATE` | `single_visual_line_without_boundary_evidence` |
| 21 | unresolved | 徐鸣同志： | `OCR_VISUAL_LINE` | `REJECTED` | `recovered:p0021:02` (1): 徐鸣同志： | `UNKNOWN` | `field_label_or_salutation` |
| 22 | unresolved | 正式版 | `OCR_VISUAL_LINE` | `REJECTED` | `recovered:p0022:01` (1): 正式版 | `UNKNOWN` | `repeated_page_decoration` |
| 23 | unresolved | 国家自然科学基金 | `OCR_VISUAL_LINE` | `AMBIGUOUS` | `recovered:p0023:01` (1): 国家自然科学基金 | `DOCUMENT_BOUNDARY_CANDIDATE` | `single_visual_line_without_boundary_evidence` |
| 26 | unresolved | ISIS | `OCR_VISUAL_LINE` | `REJECTED` | `recovered:p0026:01` (1): ISIS | `UNKNOWN` | `short_field_or_interface_fragment` |
| 26 | unresolved | 单位名称 | `OCR_VISUAL_LINE` | `REJECTED` | `recovered:p0026:02` (1): 单位名称 | `UNKNOWN` | `short_field_or_interface_fragment` |
| 26 | unresolved | 跳转至 | `OCR_VISUAL_LINE` | `REJECTED` | `recovered:p0026:03` (1): 跳转至 | `UNKNOWN` | `short_field_or_interface_fragment` |
| 27 | unresolved | 陕西省自然科学基础研究计划 | `OCR_VISUAL_LINE` | `ACCEPTED_PROPOSAL` | `recovered:p0027:01` (2): 陕西省自然科学基础研究计划 + 项目合同（任务）书 | `DOCUMENT_BOUNDARY_CANDIDATE` | `adjacent_visual_title_lines` |
| 27 | unresolved | 项目合同（任务）书 | `OCR_VISUAL_LINE` | `ACCEPTED_PROPOSAL` | `recovered:p0027:01` (2): 陕西省自然科学基础研究计划 + 项目合同（任务）书 | `DOCUMENT_BOUNDARY_CANDIDATE` | `adjacent_visual_title_lines` |
| 29 | unresolved | 陕西省教育厅服务地方专项计划项目 | `OCR_VISUAL_LINE` | `ACCEPTED_PROPOSAL` | `recovered:p0029:01` (2): 陕西省教育厅服务地方专项计划项目 + 合同书 | `DOCUMENT_BOUNDARY_CANDIDATE` | `adjacent_visual_title_lines` |
| 29 | unresolved | 合同书 | `OCR_VISUAL_LINE` | `ACCEPTED_PROPOSAL` | `recovered:p0029:01` (2): 陕西省教育厅服务地方专项计划项目 + 合同书 | `DOCUMENT_BOUNDARY_CANDIDATE` | `adjacent_visual_title_lines` |
| 30 | unresolved | 陕西省自然科学基础研究计划项目 | `OCR_VISUAL_LINE` | `ACCEPTED_PROPOSAL` | `recovered:p0030:01` (2): 陕西省自然科学基础研究计划项目 + 结题审查结果的通知 | `DOCUMENT_BOUNDARY_CANDIDATE` | `adjacent_visual_title_lines` |
| 30 | unresolved | 结题审查结果的通知 | `OCR_VISUAL_LINE` | `ACCEPTED_PROPOSAL` | `recovered:p0030:01` (2): 陕西省自然科学基础研究计划项目 + 结题审查结果的通知 | `DOCUMENT_BOUNDARY_CANDIDATE` | `adjacent_visual_title_lines` |
| 31 | unresolved | 中国博士后科学基金资助证书 | `OCR_VISUAL_LINE` | `AMBIGUOUS` | `recovered:p0031:01` (1): 中国博士后科学基金资助证书 | `DOCUMENT_BOUNDARY_CANDIDATE` | `single_visual_line_without_boundary_evidence` |
| 36 | unresolved | 陕西省国际科技合作基地 | `OCR_VISUAL_LINE` | `ACCEPTED_PROPOSAL` | `recovered:p0036:01` (2): 陕西省国际科技合作基地 + 项目协议书 | `DOCUMENT_BOUNDARY_CANDIDATE` | `adjacent_visual_title_lines` |
| 36 | unresolved | 项目协议书 | `OCR_VISUAL_LINE` | `ACCEPTED_PROPOSAL` | `recovered:p0036:01` (2): 陕西省国际科技合作基地 + 项目协议书 | `DOCUMENT_BOUNDARY_CANDIDATE` | `adjacent_visual_title_lines` |
| 38 | unresolved | 陕西省科学技术奖 | `OCR_VISUAL_LINE` | `AMBIGUOUS` | `recovered:p0038:01` (1): 陕西省科学技术奖 | `UNKNOWN` | `single_visual_line_without_boundary_evidence` |
| 39 | unresolved | 陕西省科学技术奖 | `OCR_VISUAL_LINE` | `AMBIGUOUS` | `recovered:p0039:01` (1): 陕西省科学技术奖 | `DOCUMENT_BOUNDARY_CANDIDATE` | `single_visual_line_without_boundary_evidence` |
| 41 | unresolved | HZDR | `OCR_VISUAL_LINE` | `REJECTED` | `recovered:p0041:01` (1): HZDR | `UNKNOWN` | `corner_mark_or_logo` |
| 41 | unresolved | 正式版 | `OCR_VISUAL_LINE` | `REJECTED` | `recovered:p0041:02` (1): 正式版 | `UNKNOWN` | `repeated_page_decoration` |
| 43 | unresolved | 1-kHz Repetitive Operation of Quenched High-Gain GaAs Photoconductive Semiconductor Switches at 8-nJ Excitation | `MARKDOWN_HEADING` | `AMBIGUOUS` | `recovered:p0043:01` (1): 1-kHz Repetitive Operation of Quenched High-Gain GaAs Photoconductive Semiconductor Switches at 8-nJ Excitation | `DOCUMENT_BOUNDARY_CANDIDATE` | `provider_heading_without_independent_boundary_evidence` |
| 43 | unresolved | I. INTRODUCTION | `MARKDOWN_HEADING` | `AMBIGUOUS` | `recovered:p0043:02` (1): I. INTRODUCTION | `LOCAL_HEADING` | `provider_heading_without_independent_boundary_evidence` |
| 44 | unresolved | DFT characterization and design of anthracene-based molecules for improving spectra and charge transfer | `MARKDOWN_HEADING` | `AMBIGUOUS` | `recovered:p0044:01` (1): DFT characterization and design of anthracene-based molecules for improving spectra and charge transfer | `DOCUMENT_BOUNDARY_CANDIDATE` | `provider_heading_without_independent_boundary_evidence` |
| 44 | unresolved | ARTICLE INFO | `MARKDOWN_HEADING` | `AMBIGUOUS` | `recovered:p0044:02` (1): ARTICLE INFO | `LOCAL_HEADING` | `provider_heading_without_independent_boundary_evidence` |
| 44 | unresolved | ABSTRACT | `MARKDOWN_HEADING` | `AMBIGUOUS` | `recovered:p0044:03` (1): ABSTRACT | `LOCAL_HEADING` | `provider_heading_without_independent_boundary_evidence` |
| 44 | unresolved | 1. Introduction | `MARKDOWN_HEADING` | `AMBIGUOUS` | `recovered:p0044:04` (1): 1. Introduction | `LOCAL_HEADING` | `provider_heading_without_independent_boundary_evidence` |
| 49 | unresolved | Terahertz generation and detection with InGaAs-based large-area photoconductive devices excited at 1.55 μm | `MARKDOWN_HEADING` | `AMBIGUOUS` | `recovered:p0049:01` (1): Terahertz generation and detection with InGaAs-based large-area photoconductive devices excited at 1.55 μm | `DOCUMENT_BOUNDARY_CANDIDATE` | `provider_heading_without_independent_boundary_evidence` |
| 51 | unresolved | Comparison on the Synchronization of Two Parallel GaAs Photoconductive Semiconductor Switches Excited by Laser Diodes | `MARKDOWN_HEADING` | `AMBIGUOUS` | `recovered:p0051:01` (1): Comparison on the Synchronization of Two Parallel GaAs Photoconductive Semiconductor Switches Excited by Laser Diodes | `DOCUMENT_BOUNDARY_CANDIDATE` | `provider_heading_without_independent_boundary_evidence` |
| 51 | unresolved | I. INTRODUCTION | `MARKDOWN_HEADING` | `AMBIGUOUS` | `recovered:p0051:02` (1): I. INTRODUCTION | `LOCAL_HEADING` | `provider_heading_without_independent_boundary_evidence` |
| 51 | unresolved | II. EXPERIMENTAL SETUP | `MARKDOWN_HEADING` | `AMBIGUOUS` | `recovered:p0051:03` (1): II. EXPERIMENTAL SETUP | `LOCAL_HEADING` | `provider_heading_without_independent_boundary_evidence` |
| 53 | unresolved | [ THANK YOU ] | `OCR_VISUAL_LINE` | `AMBIGUOUS` | `recovered:p0053:01` (1): [ THANK YOU ] | `UNKNOWN` | `competing_nonadjacent_candidates` |
| 53 | unresolved | Make the most of your [ MEMBERSHIP ] | `OCR_VISUAL_LINE` | `AMBIGUOUS` | `recovered:p0053:02` (1): Make the most of your [ MEMBERSHIP ] | `UNKNOWN` | `competing_nonadjacent_candidates` |
| 53 | unresolved | For Your | `OCR_VISUAL_LINE` | `AMBIGUOUS` | `recovered:p0053:03` (1): For Your | `UNKNOWN` | `competing_nonadjacent_candidates` |
| 53 | unresolved | Membership | `OCR_VISUAL_LINE` | `AMBIGUOUS` | `recovered:p0053:04` (1): Membership | `UNKNOWN` | `competing_nonadjacent_candidates` |
| 56 | unresolved | 第十六届全国高功率粒子束会议 | `OCR_VISUAL_LINE` | `AMBIGUOUS` | `recovered:p0056:01` (1): 第十六届全国高功率粒子束会议 | `DOCUMENT_BOUNDARY_CANDIDATE` | `competing_nonadjacent_candidates` |
| 56 | unresolved | 会议手册 | `OCR_VISUAL_LINE` | `AMBIGUOUS` | `recovered:p0056:02` (1): 会议手册 | `DOCUMENT_BOUNDARY_CANDIDATE` | `competing_nonadjacent_candidates` |
| 59 | unresolved | 2020年“高压放电与等离子体应用”视频系列研讨会一第22期 | `MARKDOWN_HEADING` | `AMBIGUOUS` | `recovered:p0059:01` (1): 2020年“高压放电与等离子体应用”视频系列研讨会一第22期 | `UNKNOWN` | `provider_heading_without_independent_boundary_evidence` |
| 59 | unresolved | 会议日程： | `MARKDOWN_HEADING` | `AMBIGUOUS` | `recovered:p0059:02` (1): 会议日程： | `LOCAL_HEADING` | `provider_heading_without_independent_boundary_evidence` |
| 62 | unresolved | HZDR | `OCR_VISUAL_LINE` | `REJECTED` | `recovered:p0062:01` (1): HZDR | `UNKNOWN` | `corner_mark_or_logo` |
| 64 | unresolved | 中国科学院上海微系统与信息技术研究所 | `OCR_VISUAL_LINE` | `AMBIGUOUS` | `recovered:p0064:01` (1): 中国科学院上海微系统与信息技术研究所 | `DOCUMENT_BOUNDARY_CANDIDATE` | `competing_nonadjacent_candidates` |
| 64 | unresolved | 应用证明 | `OCR_VISUAL_LINE` | `AMBIGUOUS` | `recovered:p0064:02` (1): 应用证明 | `DOCUMENT_BOUNDARY_CANDIDATE` | `competing_nonadjacent_candidates` |
| 64 | unresolved | 正式版 | `OCR_VISUAL_LINE` | `REJECTED` | `recovered:p0064:03` (1): 正式版 | `UNKNOWN` | `repeated_page_decoration` |
| 66 | unresolved | 科技成果登记表 | `OCR_VISUAL_LINE` | `ACCEPTED_PROPOSAL` | `recovered:p0066:01` (2): 科技成果登记表 + (基础理论、软科学类成果) | `DOCUMENT_BOUNDARY_CANDIDATE` | `adjacent_visual_title_lines` |
| 66 | unresolved | (基础理论、软科学类成果) | `OCR_VISUAL_LINE` | `ACCEPTED_PROPOSAL` | `recovered:p0066:01` (2): 科技成果登记表 + (基础理论、软科学类成果) | `DOCUMENT_BOUNDARY_CANDIDATE` | `adjacent_visual_title_lines` |
| 66 | unresolved | 成果名称:叉指电极式GaAs太赫兹光电导天线关键技术研究 | `OCR_VISUAL_LINE` | `REJECTED` | `recovered:p0066:02` (1): 成果名称:叉指电极式GaAs太赫兹光电导天线关键技术研究 | `UNKNOWN` | `field_label_or_salutation` |
| 66 | unresolved | 正式版 | `OCR_VISUAL_LINE` | `REJECTED` | `recovered:p0066:03` (1): 正式版 | `UNKNOWN` | `repeated_page_decoration` |

## 没有候选的重点页面

| Page | Native ownership | E4B 诊断 | E4C 结果 |
|---:|---|---|---|
| 34 | unresolved | reading blocks 存在，但 `no_heading_block` | 无 proposal |
| 35 | unresolved | reading blocks 存在，但 `no_heading_block` | 无 proposal |

## 待判边界

- 单个 OCR 视觉行即使 Provider confidence 很高，仍缺独立边界证据，通常保持 `AMBIGUOUS`。
- 同页非相邻候选会显式标注竞争；Markdown 的 level 2 保守标为 `LOCAL_HEADING`，仍保持待判。
- 跨页只读取 Native 前后页 ownership 和候选存在性；本轮不推断 page range，不修改 section_id。
- 候选 bbox 仍是 `PROVIDER_INPUT_IMAGE`，没有映射成 PDF 页面坐标。
- 现有 Native、Fallback、selected prediction、Canonical、Renderer、Audit artifact 不因本报告改变。
