# R2-E3B Page Ownership Diagnostics

依据 `outputs/template_removal_review` 中的 Stage 1 原生快照，在内存中分别运行 E3A（当前 HEAD）和 E3B 的 section discovery。诊断只用于开发核验，不进入正式 section artifact 或 Canonical schema。

`CONTINUE` 表示逐页确认归属；`NEW_SECTION` 表示原生标题锚点；`UNRESOLVED` 表示证据不足或已遇到边界。外层 `N/total` 页码仅为辅助信号，附件自带的 `- N -` 与章节条目编号组合才可跨扫描页确认归属。

## case_003

### Section ranges

| Anchor page | Observed title | E3A pages | E3B pages |
|---:|---|---|---|
| 18 | 证明材料目录 | 18–18 | 18–18 |
| 19 | 关于国家自然科学基金资助项目批准及有关事项的通知 | 19–19 | 19–19 |
| 20 | 关于国家自然科学基金资助项目批准及有关事项的通知 | 20–20 | 20–20 |
| 24 | 关于国家自然科学基金资助项目批准及有关事项的通知 | 24–24 | 24–24 |
| 28 | 红外物理国家重点实验室 | 28–28 | 28–28 |
| 65 | 军民融合及产学研合作证明 | 65–65 | 65–65 |

E3A unresolved: 1–1, 21–23, 25–27, 29–64, 66–66.
E3B unresolved: 1–1, 21–23, 25–27, 29–64, 66–66.

### Per-page decisions

| Page | Previous/observed anchor | Continuity signals | Boundary signals | Decision | Reason |
|---:|---:|---|---|---|---|
| 19 | 19 | — | observed_heading | NEW_SECTION | observed_native_heading |
| 20 | 20 | — | observed_heading | NEW_SECTION | observed_native_heading |
| 21 | 20 | pdf_page_number_consecutive, font_size_stable | page_dimensions_changed, insufficient_native_content, new_image_dominant_page | UNRESOLVED | page_dimensions_changed |
| 22 | 20 | pdf_page_number_consecutive, page_dimensions_stable, font_size_stable | insufficient_native_content | UNRESOLVED | propagation_already_stopped |
| 23 | 20 | pdf_page_number_consecutive, font_size_stable | page_dimensions_changed, insufficient_native_content | UNRESOLVED | propagation_already_stopped |
| 24 | 24 | — | observed_heading | NEW_SECTION | observed_native_heading |
| 25 | 24 | pdf_page_number_consecutive, font_size_stable | page_dimensions_changed | UNRESOLVED | page_dimensions_changed |
| 26 | 24 | pdf_page_number_consecutive, font_size_stable | page_dimensions_changed | UNRESOLVED | propagation_already_stopped |
| 27 | 24 | pdf_page_number_consecutive, page_dimensions_stable, font_size_stable | insufficient_native_content | UNRESOLVED | propagation_already_stopped |
| 28 | 28 | — | observed_heading | NEW_SECTION | observed_native_heading |
| 29 | 28 | pdf_page_number_consecutive, page_dimensions_stable, font_size_stable | insufficient_native_content | UNRESOLVED | insufficient_native_content |
| 30 | 28 | pdf_page_number_consecutive, page_dimensions_stable, font_size_stable | insufficient_native_content | UNRESOLVED | propagation_already_stopped |
| 31 | 28 | pdf_page_number_consecutive, font_size_stable | page_dimensions_changed, insufficient_native_content | UNRESOLVED | propagation_already_stopped |
| 32 | 28 | pdf_page_number_consecutive, font_size_stable | page_dimensions_changed, insufficient_native_content | UNRESOLVED | propagation_already_stopped |
| 33 | 28 | pdf_page_number_consecutive, page_dimensions_stable, font_size_stable | — | UNRESOLVED | propagation_already_stopped |
| 34 | 28 | pdf_page_number_consecutive, page_dimensions_stable, font_size_stable | — | UNRESOLVED | propagation_already_stopped |
| 35 | 28 | pdf_page_number_consecutive, page_dimensions_stable, font_size_stable | — | UNRESOLVED | propagation_already_stopped |
| 36 | 28 | pdf_page_number_consecutive, page_dimensions_stable, font_size_stable | insufficient_native_content | UNRESOLVED | propagation_already_stopped |
| 37 | 28 | pdf_page_number_consecutive, font_size_stable | page_dimensions_changed, insufficient_native_content | UNRESOLVED | propagation_already_stopped |
| 38 | 28 | pdf_page_number_consecutive, font_size_stable | page_dimensions_changed, insufficient_native_content | UNRESOLVED | propagation_already_stopped |
| 39 | 28 | pdf_page_number_consecutive, page_dimensions_stable, font_size_stable | insufficient_native_content | UNRESOLVED | propagation_already_stopped |
| 40 | 28 | pdf_page_number_consecutive, font_size_stable | page_dimensions_changed, insufficient_native_content | UNRESOLVED | propagation_already_stopped |
| 41 | 28 | pdf_page_number_consecutive, font_size_stable | page_dimensions_changed, insufficient_native_content | UNRESOLVED | propagation_already_stopped |
| 42 | 28 | pdf_page_number_consecutive, font_size_stable | page_dimensions_changed | UNRESOLVED | propagation_already_stopped |
| 43 | 28 | pdf_page_number_consecutive, page_dimensions_stable, font_size_stable | — | UNRESOLVED | propagation_already_stopped |
| 44 | 28 | pdf_page_number_consecutive, page_dimensions_stable, font_size_stable | — | UNRESOLVED | propagation_already_stopped |
| 45 | 28 | pdf_page_number_consecutive, page_dimensions_stable, font_size_stable | — | UNRESOLVED | propagation_already_stopped |
| 46 | 28 | pdf_page_number_consecutive, page_dimensions_stable, font_size_stable | — | UNRESOLVED | propagation_already_stopped |
| 47 | 28 | pdf_page_number_consecutive, font_size_stable | page_dimensions_changed, insufficient_native_content | UNRESOLVED | propagation_already_stopped |
| 48 | 28 | pdf_page_number_consecutive, page_dimensions_stable, font_size_stable | — | UNRESOLVED | propagation_already_stopped |
| 49 | 28 | pdf_page_number_consecutive, page_dimensions_stable, font_size_stable | — | UNRESOLVED | propagation_already_stopped |
| 50 | 28 | pdf_page_number_consecutive, page_dimensions_stable, font_size_stable | — | UNRESOLVED | propagation_already_stopped |
| 51 | 28 | pdf_page_number_consecutive, page_dimensions_stable, font_size_stable | — | UNRESOLVED | propagation_already_stopped |
| 52 | 28 | pdf_page_number_consecutive, font_size_stable | page_dimensions_changed | UNRESOLVED | propagation_already_stopped |
| 53 | 28 | pdf_page_number_consecutive, page_dimensions_stable, font_size_stable | new_image_dominant_page | UNRESOLVED | propagation_already_stopped |
| 54 | 28 | pdf_page_number_consecutive, font_size_stable | page_dimensions_changed, insufficient_native_content | UNRESOLVED | propagation_already_stopped |
| 55 | 28 | pdf_page_number_consecutive, page_dimensions_stable, font_size_stable | insufficient_native_content | UNRESOLVED | propagation_already_stopped |
| 56 | 28 | pdf_page_number_consecutive, page_dimensions_stable, font_size_stable | insufficient_native_content | UNRESOLVED | propagation_already_stopped |
| 57 | 28 | pdf_page_number_consecutive, page_dimensions_stable, font_size_stable | — | UNRESOLVED | propagation_already_stopped |
| 58 | 28 | pdf_page_number_consecutive, page_dimensions_stable, font_size_stable | — | UNRESOLVED | propagation_already_stopped |
| 59 | 28 | font_size_stable | page_dimensions_changed | UNRESOLVED | propagation_already_stopped |
| 60 | 28 | page_dimensions_stable, font_size_stable | insufficient_native_content | UNRESOLVED | propagation_already_stopped |
| 61 | 28 | pdf_page_number_consecutive, page_dimensions_stable, font_size_stable | insufficient_native_content | UNRESOLVED | propagation_already_stopped |
| 62 | 28 | pdf_page_number_consecutive, page_dimensions_stable, font_size_stable | — | UNRESOLVED | propagation_already_stopped |
| 63 | 28 | pdf_page_number_consecutive, page_dimensions_stable, font_size_stable | — | UNRESOLVED | propagation_already_stopped |
| 64 | 28 | pdf_page_number_consecutive, page_dimensions_stable, font_size_stable | insufficient_native_content, new_image_dominant_page | UNRESOLVED | propagation_already_stopped |
| 65 | 65 | — | observed_heading | NEW_SECTION | observed_native_heading |
| 66 | 65 | page_dimensions_stable, font_size_stable | insufficient_native_content, new_image_dominant_page | UNRESOLVED | insufficient_native_content |

## case_004

### Section ranges

| Anchor page | Observed title | E3A pages | E3B pages |
|---:|---|---|---|
| 18 | 八、附件清单 | 18–18 | 18–18 |
| 19 | 科研诚信承诺书 | 19–19 | 19–19 |
| 20 | 九、审核意见 | 20–20 | 20–20 |
| 25 | 一、科研项目证明材料 | 25–47 | 25–47 |
| 48 | 二、科研论文证明材料 | 48–79 | 48–79 |
| 80 | 三、科技奖励及荣誉证明材 | 80–89 | 80–89 |
| 90 | 四、专利证明材料 | 90–100 | 90–100 |
| 101 | 五、规范标准 | 101–101 | 101–114 |

E3A unresolved: 1–1, 21–24, 102–114.
E3B unresolved: 1–1, 21–24.

### Per-page decisions

| Page | Previous/observed anchor | Continuity signals | Boundary signals | Decision | Reason |
|---:|---:|---|---|---|---|
| 21 | 20 | pdf_page_number_consecutive, page_dimensions_stable, font_size_stable | cover_like_page, new_document_boundary_ahead | UNRESOLVED | new_document_boundary_ahead |
| 22 | 20 | pdf_page_number_consecutive, page_dimensions_stable, font_size_stable | new_document_boundary_ahead | UNRESOLVED | propagation_already_stopped |
| 23 | 20 | pdf_page_number_consecutive, page_dimensions_stable, font_size_stable | new_document_boundary_ahead | UNRESOLVED | propagation_already_stopped |
| 24 | 20 | pdf_page_number_consecutive, page_dimensions_stable, font_size_stable | new_document_boundary_ahead | UNRESOLVED | propagation_already_stopped |
| 25 | 25 | — | observed_heading | NEW_SECTION | observed_native_heading |
| 101 | 101 | — | observed_heading | NEW_SECTION | observed_native_heading |
| 102 | 101 | internal_page_number_consecutive, pdf_page_number_consecutive, page_dimensions_stable, font_size_stable, item_number_matches_section | — | CONTINUE | internal_page_and_item_number_continuity |
| 103 | 101 | internal_page_number_consecutive, pdf_page_number_consecutive, page_dimensions_stable, font_size_stable, item_number_matches_section | — | CONTINUE | internal_page_and_item_number_continuity |
| 104 | 101 | internal_page_number_consecutive, pdf_page_number_consecutive, page_dimensions_stable, font_size_stable, item_number_matches_section | — | CONTINUE | internal_page_and_item_number_continuity |
| 105 | 101 | internal_page_number_consecutive, pdf_page_number_consecutive, page_dimensions_stable, font_size_stable, item_number_matches_section | — | CONTINUE | internal_page_and_item_number_continuity |
| 106 | 101 | internal_page_number_consecutive, pdf_page_number_consecutive, page_dimensions_stable, font_size_stable, item_number_matches_section | — | CONTINUE | internal_page_and_item_number_continuity |
| 107 | 101 | internal_page_number_consecutive, pdf_page_number_consecutive, page_dimensions_stable, font_size_stable, item_number_matches_section | — | CONTINUE | internal_page_and_item_number_continuity |
| 108 | 101 | internal_page_number_consecutive, pdf_page_number_consecutive, page_dimensions_stable, font_size_stable, item_number_matches_section | — | CONTINUE | internal_page_and_item_number_continuity |
| 109 | 101 | internal_page_number_consecutive, pdf_page_number_consecutive, page_dimensions_stable, font_size_stable, item_number_matches_section | — | CONTINUE | internal_page_and_item_number_continuity |
| 110 | 101 | internal_page_number_consecutive, pdf_page_number_consecutive, page_dimensions_stable, font_size_stable, item_number_matches_section | — | CONTINUE | internal_page_and_item_number_continuity |
| 111 | 101 | internal_page_number_consecutive, pdf_page_number_consecutive, page_dimensions_stable, font_size_stable, item_number_matches_section | — | CONTINUE | internal_page_and_item_number_continuity |
| 112 | 101 | internal_page_number_consecutive, pdf_page_number_consecutive, page_dimensions_stable, font_size_stable, item_number_matches_section | — | CONTINUE | internal_page_and_item_number_continuity |
| 113 | 101 | internal_page_number_consecutive, pdf_page_number_consecutive, page_dimensions_stable, font_size_stable, item_number_matches_section | — | CONTINUE | internal_page_and_item_number_continuity |
| 114 | 101 | internal_page_number_consecutive, pdf_page_number_consecutive, page_dimensions_stable, font_size_stable, item_number_matches_section | — | CONTINUE | internal_page_and_item_number_continuity |

## Interpretation

- case_003: page 21 loses reliable native content and changes dimensions after page 20; propagation stops. Page 25 changes orientation after the page 24 anchor. Page 29 has no meaningful native content after page 28. The later heterogeneous pages do not regain ownership without another accepted anchor. The three identical notification titles on pages 19, 20 and 24 remain separate anchors.
- case_004: page 21 is a cover-like boundary and the independently observed numbering restart at page 25 prevents pages 21–24 from being claimed by page 20. Pages 102–114 have consecutive internal page numbers and 5.x item prefixes matching the observed numbered anchor on page 101.
- These are ownership decisions only. Title text is never changed or supplied by a template.

## Quality checks

- E3A/E3B Stage 5 `result.json` is exactly equal for both cases.
- TextFlow record text, source pages, and source word indices are exactly equal: case_003 has 631 records; case_004 has 295.
- Evidence word accounting and Quality summary are equal for both cases. Fallback task ID, type, and page sequences are equal: 53 tasks for case_003 and 92 for case_004.
- Rebuilding case_004 Canonical with the same selected predictions preserves all 295 record IDs, text, source pages, and source word indices, as well as fallback overlays and document status. Section metadata differs because pages 102–114 now belong to the observed page 101 section.
