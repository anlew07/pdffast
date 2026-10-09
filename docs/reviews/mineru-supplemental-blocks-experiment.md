# MinerU supplemental blocks 离线实验 A

日期：2026-10-09。未调用模型，未接入正式 Pipeline，未改 Markdown 或生产 Normalizer。

## 输入、依据及复现

完整阅读质量归因、两页验证和性能诊断三份报告。输入为 `outputs/mineru_case003_pages43_44_validation/run_3fe3efd98b/page_{43,44}/` 下冻结 middle/content_list/content_list_v2、document.md、normalized_prediction.json，以及历史 Marker canonical；Native 来自 `outputs/service/api_c20df2b1a1e345439edbf6070a671859/01_stage1/page_snapshot.jsonl`。

原型：`experiments/case003_quality/offline.py`、驱动 `run.py`、测试 `test_offline.py`。输出：`outputs/case003_content_quality_experiments/`。input_manifest.json 保存实际读取输入的绝对路径和 SHA256；原始输入不写入。离线读取这些文件合法，但本实现不得进入生产 Runtime 作为文件总线。

```bash
PYTHONPATH="$PWD" PYTHONDONTWRITEBYTECODE=1 /Users/admin/Workspace/pdffast-v2/.venv/bin/python experiments/case003_quality/run.py
```

## 原始结构和对象边界

MinerU 3.4.5 将 page_footnote/header/footer/page_number/aside_text 放入 discarded_blocks。Markdown 导出只用 para_blocks，content_list/v2 同时包含 discarded。脚注不是模型没有识别，而是已识别文字未进入 Worker Markdown。

当前 RawProviderResult 有 provider/task_id/status/payload/markdown/elapsed_seconds/warnings。Worker 从 markdown_path 取 text，raw_refs 只是旁路引用；normalize_mineru 消费 text 提取 reading_blocks，并不消费 supplemental blocks。本实验实例化真正的 RawProviderResult，把显式补充对象放进 payload，由**独立离线 evidence consumer**读取；生产 Normalizer 没有变化，也没有宣称当前已支持新字段。

建议合同（实验版本 experimental_0，不是新公开 schema）：

| 字段 | 语义 |
|---|---|
| payload.supplemental_contract_version | 可选版本；缺失表示现有 Markdown-only 输入 |
| payload.supplemental_blocks | 可选列表，合法空列表不触发文件回读 |
| original_type / role | 原 page_footnote / FOOTNOTE_EVIDENCE，不能混同正文或章节 |
| page | 真实物理页 43/44，不采用印刷页码 |
| bbox / bbox_space / page_size | MinerU 页面坐标及单位空间；不能直接当图像像素或PDF原生点 |
| provider / source / source_ref / source_index | Provider ID、冻结来源、JSON pointer、原 index；未来生产用对象来源标识，不要求路径存在 |
| text | 已识别文字，未进行事实修正 |
| local_order / body_order | 几何候选排序与正文相对顺序分别表达 |

未来应由 Worker 在推理完成时构造这些对象 → RawProviderResult → Normalizer 的结构化补充证据。raw JSON 继续旁路输出；下游不得为了对象参数缺省再回读同次运行 raw_refs。

## 实际恢复结果

| 页面 | 恢复 page_footnote | 排除非脚注块 | 原 index → 几何候选排序 | 顺序状态 |
|---|---:|---:|---|---|
| 43 | 4 | 4 | 14、15、16、17 | 全部 local_order=UNRESOLVED_OVERLAP，body_order=UNRESOLVED |
| 44 | 3 | 9 | **28、27、29** | 同上 |

第43页恢复：manuscript/资助、机构与三封邮件、在线版本说明及URL、DOI。第44页恢复：单星通讯作者及机构、双星通讯作者、两封邮件。原始类型、物理页、bbox、provider、来源指针全部保存。

两页脚注在左栏；相邻 bbox 轻微重叠，原型保守标记未知顺序，而非声称可靠全序。第44页原 index27 位于 index28 的下方，直接按 index 排会反转通讯作者次序；几何候选改为28→27→29，但未提升为正式阅读顺序。

`page_43_review.md` / `page_44_review.md` 可阅读恢复证据；`page_*_supplemental.json` 包含块和跳过原因，`page_*_object_handoff.json` 证明经过 RawProviderResult 对象交接且 markdown_unchanged=true。没有把 discarded 拼入 Markdown。

## 分类、去重和未知顺序

- 仅显式 page_footnote 进入补充证据。header/footer/page_number 不进正文；第44页 DOI 属 footer，所以**本实验未恢复该 DOI**，不得把3个脚注恢复当全部内容覆盖。
- 文本做 Unicode规范、断词换行和展示符号消除，只用于保守去重，不重写恢复文字。与 Markdown 内容重复或 raw重复文本时跳过并记录 DUPLICATE_TEXT_CONSERVATIVE。
- 空文字/无有效bbox跳过；未知类型记录 UNKNOWN_TYPE，作者、公式、reference 等不套脚注规则，保留跳过理由。
- 双栏脚注或几何重叠显式 UNRESOLVED_MULTICOLUMN/UNRESOLVED_OVERLAP。几何顺序只是候选，不自动插入正文。
- 相同脚注文字在不同位置可能合法：当前文本去重会过度合并，是**已知漏保留风险**。未来必须 text+page+region+source身份去重，不能把该原型当生产通用去重器。
- 去除标点会把少量不同公式或脚注误判相同；拼字/间隔差异也可能漏去重。未知复杂嵌套span不会自动猜。作者署名、引用、公式有独立结构语义，应分别建合同；恢复脚注无法修复本次姓名首字母或化学式错误。

## 成功、未覆盖及人工确认

冻结输入7个 page_footnote 块全部恢复为补充证据；测试重复一次 raw、已在 Markdown 中的脚注均不再次加入。这个“7/7”只指枚举的原生块，不是字符准确率、通用 recall 或所有 PDF脚注覆盖率。

没有人工全文字符真值，未统计 precision/recall。文本源本身仍可能识别错误；阅读顺序尤其与双栏正文的关系须人工确认。页眉页脚和出版DOI未自动恢复，正文漏句、姓名、公式也未修复。

## 测试及生产建议

11个离线测试包括真实两页7块、脚注来源/bbox、已有MD去重、raw重复、未知类型、空结构、几何顺序、双栏/重叠未知顺序、Native非真值、公式不修正、Markdown-only、断词和页眉负样本。加原 Normalizer/object handoff/Executor/reference parity 测试：**45 passed，0 failed，1.86秒**；其中11个离线、34个既有测试。

推荐下一阶段只将**补充证据对象及来源记账**作为候选内部接口，不让它立即影响 Canonical正文。若获确认，再完善空间去重、复杂块schema校验、阅读顺序和兼容测试，才考虑生产接入。现有缺字段输入必须保持原结果，不新增公共HTTP字段。

本轮未改 pdffast/ 任何生产文件、Router/Policy/Acceptance/Canonical/HTTP；未运行真实模型或完整case_003，未提交、清理、修改v2/JudgeAI。
