# R2-E4B case_003 recovered heading candidate review

由现有 selected predictions 生成；没有重跑 Provider。Candidate 不是 section。本轮没有修改 Native ownership、Canonical、Renderer 或 unresolved。

- All pages: 46 candidates: {'OCR_VISUAL_LINE': 34, 'MARKDOWN_HEADING': 12}.
- Requested focus pages: 42 candidates: {'OCR_VISUAL_LINE': 30, 'MARKDOWN_HEADING': 12}.
- Rejected diagnostics (all pages): {'not_whole_page_fallback': 23, 'not_visually_prominent': 559, 'fragment_or_dense_line': 103, 'low_confidence': 46, 'native_section_already_owned': 1, 'no_heading_block': 2}.
- 本样本中 12 个 Markdown 衍生 heading block 均保留为候选，heading block 被拒绝数为 0；这不表示任何一个已成为章节。34、35 页没有 heading block；43、44、49、51、59 页分别产生 2、4、1、3、2 个。`ARTICLE INFO`、`ABSTRACT` 等是页内标题证据，不能直接等同文档章节。
- 本样本未发现能仅凭 normalized 内容确认为“整句正文误标 heading”的实例；历史参考样本 `outputs/9_5_canonical_predictions/mineru_local/s9_0035_inline_context_fallback_6c862cacae60.json` 把“为N张连续帧中面部ROI的差……”标成 heading。它是局部 task，本轮会排除；这个事实仍说明 Provider heading 不能直接升级。OCR rejected line 数只用于诊断。

## Focus pages: candidate evidence

| Page | Native ownership | Provider / task | Evidence kind | Candidate text | Signals | Status / reason |
|---:|---|---|---|---|---|---|
| 21 | unresolved | `rapidocr_ch_light` / `s9_0021_page_fallback_442cdbc188b8` | `OCR_VISUAL_LINE` | 国家自然科学基金资助项目批准通知 | relative_line_height=1.2059; top_in_ocr_extent=0.0712; center_offset=0.0082; score=0.6252; bbox=PROVIDER_INPUT_IMAGE | `CANDIDATE` / not accepted |
| 21 | unresolved | `rapidocr_ch_light` / `s9_0021_page_fallback_442cdbc188b8` | `OCR_VISUAL_LINE` | 徐鸣同志： | relative_line_height=1.2941; top_in_ocr_extent=0.1401; center_offset=0.2171; score=0.6024; bbox=PROVIDER_INPUT_IMAGE | `CANDIDATE` / not accepted |
| 22 | unresolved | `rapidocr_ch_light` / `s9_0022_page_fallback_913012a2a737` | `OCR_VISUAL_LINE` | 正式版 | relative_line_height=15.0857; top_in_ocr_extent=0.3251; center_offset=0.0144; score=0.69; bbox=PROVIDER_INPUT_IMAGE | `CANDIDATE` / not accepted |
| 23 | unresolved | `rapidocr_ch_light` / `s9_0023_page_fallback_c327a886fa79` | `OCR_VISUAL_LINE` | 国家自然科学基金 | relative_line_height=1.2549; top_in_ocr_extent=0.0651; center_offset=0.0017; score=0.6326; bbox=PROVIDER_INPUT_IMAGE | `CANDIDATE` / not accepted |
| 26 | unresolved | `rapidocr_ch_light` / `s9_0026_page_fallback_4ab1758da51e` | `OCR_VISUAL_LINE` | ISIS | relative_line_height=1.2609; top_in_ocr_extent=0.0297; center_offset=0.1995; score=0.6138; bbox=PROVIDER_INPUT_IMAGE | `CANDIDATE` / not accepted |
| 26 | unresolved | `rapidocr_ch_light` / `s9_0026_page_fallback_4ab1758da51e` | `OCR_VISUAL_LINE` | 单位名称 | relative_line_height=1.3043; top_in_ocr_extent=0.1141; center_offset=0.1415; score=0.6159; bbox=PROVIDER_INPUT_IMAGE | `CANDIDATE` / not accepted |
| 26 | unresolved | `rapidocr_ch_light` / `s9_0026_page_fallback_4ab1758da51e` | `OCR_VISUAL_LINE` | 跳转至 | relative_line_height=1.2174; top_in_ocr_extent=0.3448; center_offset=0.1446; score=0.5774; bbox=PROVIDER_INPUT_IMAGE | `CANDIDATE` / not accepted |
| 27 | unresolved | `rapidocr_ch_light` / `s9_0027_page_fallback_0260f9ae5126` | `OCR_VISUAL_LINE` | 陕西省自然科学基础研究计划 | relative_line_height=1.726; top_in_ocr_extent=0.2307; center_offset=0.0013; score=0.6693; bbox=PROVIDER_INPUT_IMAGE | `CANDIDATE` / not accepted |
| 27 | unresolved | `rapidocr_ch_light` / `s9_0027_page_fallback_0260f9ae5126` | `OCR_VISUAL_LINE` | 项目合同（任务）书 | relative_line_height=1.6438; top_in_ocr_extent=0.29; center_offset=0.0013; score=0.6523; bbox=PROVIDER_INPUT_IMAGE | `CANDIDATE` / not accepted |
| 29 | unresolved | `rapidocr_ch_light` / `s9_0029_page_fallback_9ca6452f49a8` | `OCR_VISUAL_LINE` | 陕西省教育厅服务地方专项计划项目 | relative_line_height=1.3462; top_in_ocr_extent=0.0; center_offset=0.0395; score=0.6468; bbox=PROVIDER_INPUT_IMAGE | `CANDIDATE` / not accepted |
| 29 | unresolved | `rapidocr_ch_light` / `s9_0029_page_fallback_9ca6452f49a8` | `OCR_VISUAL_LINE` | 合同书 | relative_line_height=1.5; top_in_ocr_extent=0.0298; center_offset=0.0405; score=0.6616; bbox=PROVIDER_INPUT_IMAGE | `CANDIDATE` / not accepted |
| 30 | unresolved | `rapidocr_ch_light` / `s9_0030_page_fallback_9ea797c3cdd5` | `OCR_VISUAL_LINE` | 陕西省自然科学基础研究计划项目 | relative_line_height=1.5789; top_in_ocr_extent=0.0; center_offset=0.0513; score=0.6733; bbox=PROVIDER_INPUT_IMAGE | `CANDIDATE` / not accepted |
| 30 | unresolved | `rapidocr_ch_light` / `s9_0030_page_fallback_9ea797c3cdd5` | `OCR_VISUAL_LINE` | 结题审查结果的通知 | relative_line_height=1.5263; top_in_ocr_extent=0.0491; center_offset=0.0498; score=0.6613; bbox=PROVIDER_INPUT_IMAGE | `CANDIDATE` / not accepted |
| 31 | unresolved | `rapidocr_ch_light` / `s9_0031_page_fallback_a62a1443f09e` | `OCR_VISUAL_LINE` | 中国博士后科学基金资助证书 | relative_line_height=1.9667; top_in_ocr_extent=0.1738; center_offset=0.0466; score=0.69; bbox=PROVIDER_INPUT_IMAGE | `CANDIDATE` / not accepted |
| 36 | unresolved | `rapidocr_ch_light` / `s9_0036_page_fallback_e2a7405350fc` | `OCR_VISUAL_LINE` | 陕西省国际科技合作基地 | relative_line_height=1.7073; top_in_ocr_extent=0.0694; center_offset=0.0032; score=0.6862; bbox=PROVIDER_INPUT_IMAGE | `CANDIDATE` / not accepted |
| 36 | unresolved | `rapidocr_ch_light` / `s9_0036_page_fallback_e2a7405350fc` | `OCR_VISUAL_LINE` | 项目协议书 | relative_line_height=1.7561; top_in_ocr_extent=0.0887; center_offset=0.0032; score=0.6897; bbox=PROVIDER_INPUT_IMAGE | `CANDIDATE` / not accepted |
| 38 | unresolved | `rapidocr_ch_light` / `s9_0038_page_fallback_09786497f5bd` | `OCR_VISUAL_LINE` | 陕西省科学技术奖 | relative_line_height=1.9138; top_in_ocr_extent=0.2405; center_offset=0.0453; score=0.6854; bbox=PROVIDER_INPUT_IMAGE | `CANDIDATE` / not accepted |
| 39 | unresolved | `rapidocr_ch_light` / `s9_0039_page_fallback_976a4c66dce5` | `OCR_VISUAL_LINE` | 陕西省科学技术奖 | relative_line_height=1.7258; top_in_ocr_extent=0.0; center_offset=0.056; score=0.69; bbox=PROVIDER_INPUT_IMAGE | `CANDIDATE` / not accepted |
| 41 | unresolved | `rapidocr_ch_light` / `s9_0041_page_fallback_4f9e4f69de66` | `OCR_VISUAL_LINE` | HZDR | relative_line_height=1.64; top_in_ocr_extent=0.0; center_offset=0.455; score=0.6322; bbox=PROVIDER_INPUT_IMAGE | `CANDIDATE` / not accepted |
| 41 | unresolved | `rapidocr_ch_light` / `s9_0041_page_fallback_4f9e4f69de66` | `OCR_VISUAL_LINE` | 正式版 | relative_line_height=12.84; top_in_ocr_extent=0.3492; center_offset=0.0105; score=0.69; bbox=PROVIDER_INPUT_IMAGE | `CANDIDATE` / not accepted |
| 43 | unresolved | `mineru_local` / `s9_0043_page_fallback_5aba61185609` | `MARKDOWN_HEADING` | 1-kHz Repetitive Operation of Quenched High-Gain GaAs Photoconductive Semiconductor Switches at 8-nJ Excitation | block_index=0; level=1; origin=provider_markdown_via_normalizer; score=0.7 | `CANDIDATE` / not accepted |
| 43 | unresolved | `mineru_local` / `s9_0043_page_fallback_5aba61185609` | `MARKDOWN_HEADING` | I. INTRODUCTION | block_index=5; level=2; origin=provider_markdown_via_normalizer; score=0.7 | `CANDIDATE` / not accepted |
| 44 | unresolved | `mineru_local` / `s9_0044_page_fallback_4fedefb0cbce` | `MARKDOWN_HEADING` | DFT characterization and design of anthracene-based molecules for improving spectra and charge transfer | block_index=0; level=1; origin=provider_markdown_via_normalizer; score=0.7 | `CANDIDATE` / not accepted |
| 44 | unresolved | `mineru_local` / `s9_0044_page_fallback_4fedefb0cbce` | `MARKDOWN_HEADING` | ARTICLE INFO | block_index=8; level=2; origin=provider_markdown_via_normalizer; score=0.7 | `CANDIDATE` / not accepted |
| 44 | unresolved | `mineru_local` / `s9_0044_page_fallback_4fedefb0cbce` | `MARKDOWN_HEADING` | ABSTRACT | block_index=10; level=2; origin=provider_markdown_via_normalizer; score=0.7 | `CANDIDATE` / not accepted |
| 44 | unresolved | `mineru_local` / `s9_0044_page_fallback_4fedefb0cbce` | `MARKDOWN_HEADING` | 1. Introduction | block_index=13; level=2; origin=provider_markdown_via_normalizer; score=0.7 | `CANDIDATE` / not accepted |
| 49 | unresolved | `mineru_local` / `s9_0049_page_fallback_9c2b39d10fa8` | `MARKDOWN_HEADING` | Terahertz generation and detection with InGaAs-based large-area photoconductive devices excited at 1.55 μm | block_index=0; level=1; origin=provider_markdown_via_normalizer; score=0.7 | `CANDIDATE` / not accepted |
| 51 | unresolved | `mineru_local` / `s9_0051_page_fallback_68670adee3aa` | `MARKDOWN_HEADING` | Comparison on the Synchronization of Two Parallel GaAs Photoconductive Semiconductor Switches Excited by Laser Diodes | block_index=0; level=1; origin=provider_markdown_via_normalizer; score=0.7 | `CANDIDATE` / not accepted |
| 51 | unresolved | `mineru_local` / `s9_0051_page_fallback_68670adee3aa` | `MARKDOWN_HEADING` | I. INTRODUCTION | block_index=4; level=2; origin=provider_markdown_via_normalizer; score=0.7 | `CANDIDATE` / not accepted |
| 51 | unresolved | `mineru_local` / `s9_0051_page_fallback_68670adee3aa` | `MARKDOWN_HEADING` | II. EXPERIMENTAL SETUP | block_index=10; level=2; origin=provider_markdown_via_normalizer; score=0.7 | `CANDIDATE` / not accepted |
| 53 | unresolved | `rapidocr_ch_light` / `s9_0053_page_fallback_73ac97490afa` | `OCR_VISUAL_LINE` | [ THANK YOU ] | relative_line_height=3.5758; top_in_ocr_extent=0.0; center_offset=0.3067; score=0.69; bbox=PROVIDER_INPUT_IMAGE | `CANDIDATE` / not accepted |
| 53 | unresolved | `rapidocr_ch_light` / `s9_0053_page_fallback_73ac97490afa` | `OCR_VISUAL_LINE` | Make the most of your [ MEMBERSHIP ] | relative_line_height=1.7879; top_in_ocr_extent=0.0159; center_offset=0.1999; score=0.6787; bbox=PROVIDER_INPUT_IMAGE | `CANDIDATE` / not accepted |
| 53 | unresolved | `rapidocr_ch_light` / `s9_0053_page_fallback_73ac97490afa` | `OCR_VISUAL_LINE` | For Your | relative_line_height=2.3939; top_in_ocr_extent=0.0795; center_offset=0.3953; score=0.69; bbox=PROVIDER_INPUT_IMAGE | `CANDIDATE` / not accepted |
| 53 | unresolved | `rapidocr_ch_light` / `s9_0053_page_fallback_73ac97490afa` | `OCR_VISUAL_LINE` | Membership | relative_line_height=3.0606; top_in_ocr_extent=0.1322; center_offset=0.347; score=0.69; bbox=PROVIDER_INPUT_IMAGE | `CANDIDATE` / not accepted |
| 56 | unresolved | `rapidocr_ch_light` / `s9_0056_page_fallback_fa1a0153c522` | `OCR_VISUAL_LINE` | 第十六届全国高功率粒子束会议 | relative_line_height=1.4333; top_in_ocr_extent=0.0; center_offset=0.0196; score=0.6597; bbox=PROVIDER_INPUT_IMAGE | `CANDIDATE` / not accepted |
| 56 | unresolved | `rapidocr_ch_light` / `s9_0056_page_fallback_fa1a0153c522` | `OCR_VISUAL_LINE` | 会议手册 | relative_line_height=14.1333; top_in_ocr_extent=0.0463; center_offset=0.0196; score=0.69; bbox=PROVIDER_INPUT_IMAGE | `CANDIDATE` / not accepted |
| 59 | unresolved | `mineru_local` / `s9_0059_page_fallback_72b055c260ca` | `MARKDOWN_HEADING` | 2020年“高压放电与等离子体应用”视频系列研讨会一第22期 | block_index=11; level=1; origin=provider_markdown_via_normalizer; score=0.7 | `CANDIDATE` / not accepted |
| 59 | unresolved | `mineru_local` / `s9_0059_page_fallback_72b055c260ca` | `MARKDOWN_HEADING` | 会议日程： | block_index=18; level=2; origin=provider_markdown_via_normalizer; score=0.7 | `CANDIDATE` / not accepted |
| 62 | unresolved | `rapidocr_ch_light` / `s9_0062_page_fallback_08283a17000a` | `OCR_VISUAL_LINE` | HZDR | relative_line_height=2.4615; top_in_ocr_extent=0.0; center_offset=0.3639; score=0.69; bbox=PROVIDER_INPUT_IMAGE | `CANDIDATE` / not accepted |
| 64 | unresolved | `rapidocr_ch_light` / `s9_0064_page_fallback_c08f22891e19` | `OCR_VISUAL_LINE` | 中国科学院上海微系统与信息技术研究所 | relative_line_height=1.8049; top_in_ocr_extent=0.0; center_offset=0.0638; score=0.69; bbox=PROVIDER_INPUT_IMAGE | `CANDIDATE` / not accepted |
| 64 | unresolved | `rapidocr_ch_light` / `s9_0064_page_fallback_c08f22891e19` | `OCR_VISUAL_LINE` | 应用证明 | relative_line_height=1.3659; top_in_ocr_extent=0.1189; center_offset=0.0237; score=0.6368; bbox=PROVIDER_INPUT_IMAGE | `CANDIDATE` / not accepted |
| 64 | unresolved | `rapidocr_ch_light` / `s9_0064_page_fallback_c08f22891e19` | `OCR_VISUAL_LINE` | 正式版 | relative_line_height=11.5366; top_in_ocr_extent=0.3446; center_offset=0.0533; score=0.69; bbox=PROVIDER_INPUT_IMAGE | `CANDIDATE` / not accepted |

## Pages with no candidate or rejected OCR lines

| Page | Native ownership | Candidate count | Rejected diagnostics (reason: count) |
|---:|---|---:|---|
| 21 | unresolved | 2 | fragment_or_dense_line: 3, low_confidence: 1, not_visually_prominent: 17 |
| 22 | unresolved | 1 | fragment_or_dense_line: 2, not_visually_prominent: 23 |
| 23 | unresolved | 1 | fragment_or_dense_line: 2, low_confidence: 1, not_visually_prominent: 12 |
| 25 | unresolved | 0 | not_whole_page_fallback: 2 |
| 26 | unresolved | 3 | fragment_or_dense_line: 18, low_confidence: 2, not_visually_prominent: 50 |
| 27 | unresolved | 2 | fragment_or_dense_line: 2, not_visually_prominent: 16 |
| 29 | unresolved | 2 | fragment_or_dense_line: 9, low_confidence: 4, not_visually_prominent: 21 |
| 30 | unresolved | 2 | fragment_or_dense_line: 4, low_confidence: 2, not_visually_prominent: 14 |
| 31 | unresolved | 1 | fragment_or_dense_line: 2, low_confidence: 1, not_visually_prominent: 12 |
| 32 | unresolved | 0 | not_whole_page_fallback: 3 |
| 33 | unresolved | 0 | none (no selected page task or no rejected line) |
| 34 | unresolved | 0 | no_heading_block: 1 |
| 35 | unresolved | 0 | no_heading_block: 1 |
| 36 | unresolved | 2 | fragment_or_dense_line: 13, low_confidence: 2, not_visually_prominent: 51 |
| 37 | unresolved | 0 | fragment_or_dense_line: 2, low_confidence: 1, not_visually_prominent: 7 |
| 38 | unresolved | 1 | fragment_or_dense_line: 3, not_visually_prominent: 8 |
| 39 | unresolved | 1 | fragment_or_dense_line: 5, not_visually_prominent: 9 |
| 40 | unresolved | 0 | fragment_or_dense_line: 4, low_confidence: 1, not_visually_prominent: 8 |
| 41 | unresolved | 2 | fragment_or_dense_line: 14, low_confidence: 2, not_visually_prominent: 46 |
| 42 | unresolved | 0 | not_whole_page_fallback: 2 |
| 43 | unresolved | 2 | none (no selected page task or no rejected line) |
| 44 | unresolved | 4 | none (no selected page task or no rejected line) |
| 45 | unresolved | 0 | not_whole_page_fallback: 1 |
| 46 | unresolved | 0 | not_whole_page_fallback: 1 |
| 47 | unresolved | 0 | not_whole_page_fallback: 2 |
| 48 | unresolved | 0 | not_whole_page_fallback: 1 |
| 49 | unresolved | 1 | none (no selected page task or no rejected line) |
| 50 | unresolved | 0 | none (no selected page task or no rejected line) |
| 51 | unresolved | 3 | none (no selected page task or no rejected line) |
| 52 | unresolved | 0 | not_whole_page_fallback: 2 |
| 53 | unresolved | 4 | low_confidence: 1, not_visually_prominent: 74 |
| 54 | unresolved | 0 | fragment_or_dense_line: 3, low_confidence: 2, not_visually_prominent: 1 |
| 55 | unresolved | 0 | fragment_or_dense_line: 5, low_confidence: 6, not_visually_prominent: 1 |
| 56 | unresolved | 2 | fragment_or_dense_line: 7, not_visually_prominent: 54 |
| 57 | unresolved | 0 | not_whole_page_fallback: 2 |
| 58 | unresolved | 0 | none (no selected page task or no rejected line) |
| 59 | unresolved | 2 | none (no selected page task or no rejected line) |
| 60 | unresolved | 0 | fragment_or_dense_line: 2, not_visually_prominent: 27 |
| 61 | unresolved | 0 | low_confidence: 19, not_visually_prominent: 2 |
| 62 | unresolved | 1 | not_visually_prominent: 66 |
| 63 | unresolved | 0 | not_whole_page_fallback: 2 |
| 64 | unresolved | 3 | fragment_or_dense_line: 1, low_confidence: 1, not_visually_prominent: 16 |

## Page 29 evidence boundary

- Native profile reports 9 characters; selected RapidOCR result has 257 recovered text characters and 36 spatial OCR items.
- “陕西省教育厅服务地方专项计划项目” and “合同书” are both `OCR_VISUAL_LINE` candidates. Their raw boxes are in `PROVIDER_INPUT_IMAGE` coordinates. `top_in_observed_ocr_extent` is relative to the OCR item union, not to PDF page coordinates.
- Both remain on an unresolved Native page. No candidate creates a section or changes the page range.

## Interpretation limits

- MinerU headings in this sample come from Markdown block segmentation. They are `MARKDOWN_HEADING`, not direct PDF heading facts.
- OCR visual signals are geometry and OCR confidence, not font size or proof of a chapter. “正式版”, short labels and other false positives show why E4C needs independent acceptance and conflict checks.
- Pure text without reading blocks or spatial geometry yields `no_structural_heading_evidence`; REGION, INLINE and terminal tasks are outside this version.
- The diagnostic is read-only and is not part of `document.json`, Markdown or Canonical schema.
