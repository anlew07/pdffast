# case_003 第 43、44 页质量缺陷归因与接受机制审查

日期：2026-10-09。范围：既有产物取证、纯计算接受判断和相关测试；未重新运行模型、完整 Pipeline 或其他页。

## 1. 总结

结论分两类，不能全部归因于 OCR：

1. 人名、正文缺句、公式和机构标记：MinerU 原生 middle JSON 的文本/公式 spans 已错误或缺失，PDFFast Normalizer 延续了这些结果。归属 **A（Provider 原始输出问题）+ D（接受机制未检出）**。现有证据不能进一步区分 MinerU 内部检测、裁剪、OCR、公式识别等具体子模型责任；细分归属为 E。
2. 脚注：原生识别结果存在，但 MinerU Markdown 导出选择性排除 `discarded_blocks`，Worker 以该 Markdown 作为 RawProviderResult.text；Normalizer 按当前 Markdown 输入合同处理，不读取旁路 raw JSON。属于 **Provider 导出/PDFFast 输入表示选择造成的可恢复信息损失 + D**，并非 Normalizer 把已收到的脚注文字删除。不能笼统标成 B。

本轮未实施生产修复：没有确认当前 Markdown → normalized 转换存在本次脚注丢失的局部实现错误。若恢复结构化 raw 脚注，需要显式扩充 Provider → Normalizer 的对象输入、选择与阅读顺序/去重合同；直接读旁路文件或全部拼接 raw 会破坏边界并混入页眉、页码、重复文字。本报告给出最小后续实验，不擅自改变该合同。

## 2. 证据来源及追踪范围

已阅读：`case003-performance-diagnosis.md`、`mineru-runtime-dependency-fix.md`、`mineru-case003-pages43-44-validation.md`。

- 原 PDF：`/Users/admin/Workspace/pdffast/benchmark/samples/real/case_003.pdf`，物理第 43、44 页；页内印刷的 42/65、43/65 不是任务 page_number。
- 原任务输入：`outputs/service/api_c20df2b1a1e345439edbf6070a671859/09_1_fallback_units/inputs/page/p0043_page.png`、`p0044_page.png`；两张图本轮均实际查看。
- 新 MinerU：`outputs/mineru_case003_pages43_44_validation/run_3fe3efd98b/page_43/`、`page_44/` 的 middle/content lists、Worker Markdown、normalized、verification。
- Native：历史 `01_stage1/page_snapshot.jsonl` 的 page record；Native text 字符数 5278 / 4647。另用已安装 pypdfium2 直接打开原 PDF，文本字符数 5696 / 5089；提取引擎、空白和编码不同，不用长度差判断内容质量。
- 历史 Marker：实验目录内归档 `historical_marker_canonical.json`、`historical_marker_text.md`；历史完整运行 `10_1_canonical/canonical_document.json`、`result/document.md`。不把可覆盖的临时 Provider 输出当作历史证据。
- 本轮逐块证据：`outputs/case003_quality_acceptance_diagnosis/trace.json`，保存 Native text、原生 para_blocks、discarded 类型/bbox/index/text、当前 `_evaluate` 结果和历史 Canonical Provider。

**本次两页 MinerU 独立执行没有进入完整 Canonical/Renderer。** 因此没有与其对应的新最终 document.json/document.md；实验目录的 document.md 是 Worker Markdown。不能把历史 Marker 的最终输出当作新 MinerU 的渲染结果。C 类损失在本次新结果上没有证据。

## 3. 第 43 页逐项追踪

| 差异 | 原图/PDF 与 Native | MinerU raw → normalized | Marker 与下游证据 | 归属/可修复性 |
|---|---|---|---|---|
| 作者 Chengang Dong 首字母 | 原图可读；Native `MingXu,ChengangDong,andWeiShi` | middle text span 已为 `hengang Dong`；Worker MD 与 normalized 延续 | Marker 为 Chengang Dong；历史 Canonical 选择 Marker | A+D；Normalizer 没有正确 C 可恢复。Native 可提供冲突信号，但不能自动认定姓名真值 |
| Introduction 首字母和整句段 | 原图 THE；Native 保留 `sourcesisofimportantscientificandtechnicalinterestfor`，但双栏交错 | middle para 以 `HE development ... generation` 后直接续 `a large variety ...`；全 middle 未找到完整缺失句段，MD/normalized 同缺 | Marker 保留该句段；历史最终 Markdown 可找到完整句段 | A+D；可能检测/OCR/内部组段问题，具体子阶段 E；不能通过 Markdown Normalizer凭空补句 |
| 数量级 10^8 | 原图 10^8；Native 有数字/版面证据但非可靠 LaTeX 真值 | middle formula span 已为 `1 \\dot { 0 } ^ { 8 }`，MD/normalized 保留 | Marker 此处更接近原图；公式数不能证明准确 | A+D；模型/原始识别改善，符号冲突仅为风险信号 |
| 资助、机构、邮件、DOI、在线链接 | 原图存在；Native 也含 manuscript、机构/DOI | middle 有 **4 个 page_footnote**；content_list/v2 也保留；Worker MD 未包含，normalized 未包含 | Marker 保留主要脚注；其在线链接有缺失、脚注插入左右栏之间，亦非完美真值 | Provider MD 导出选择损失+D；信息可恢复，非已收到文本被 Normalizer删掉 |
| 期刊页眉、版权/页码 | 原图/Native 存在 | raw header/footer/page_number；MD 不含 | Marker 同样非逐字保留全部页眉页脚 | 选择性导出；需分类，不能默认全是正文遗漏 |

正确保留：论文标题、摘要主体、Index Terms、Introduction 标题、主要左右栏正文和段落延续。没有据抽查发现整个正文栏消失；这不抵消明确缺句。

## 4. 第 44 页逐项追踪

| 差异 | 原图/PDF 与 Native | MinerU raw → normalized | Marker 与下游证据 | 归属/可修复性 |
|---|---|---|---|---|
| 作者机构 b、机构前缀 c | 原图 Qungui Wang 上标 b；Native `Qungui Wang b`、`cCollegeofScience` | middle 作者 span 已缺 b，College of Science span 已缺 c；MD/normalized 同缺 | Marker 保留对应标记；双方 relations UNSUPPORTED | A+D；可用 Native做对齐冲突，不自动猜作者关系 |
| nano-TiO₂ | 原图化学式可读；Native 有 TiO2 但提取顺序交错 | middle formula 已为 `\\mathbf { \\cdot } \\Gamma \\mathbf { i } 0 _ { 2 }`；MD/normalized 保留 | Marker nano-TiO2 更接近原图；历史最终 Markdown 保留 TiO 下标 | A+D；不是 Normalizer把 Ti 改成 Gamma |
| I₃⁻ 电荷 | 原图负电荷清楚；Native 为 `I(cid:1)` 和独立 3，不能当准确公式真值 | middle 已为 `I3`，MD/normalized 同样缺电荷 | Marker 有 I_3^-；需原图裁片确认语义 | A+D；Native异常编码可告警，不能据此自动修公式 |
| 通讯作者和邮件 | 原图/Native 存在 | **3 个 page_footnote**，含 bbox/index/lines/spans、content_list/v2 同有；MD/normalized 不含 | Marker 和历史最终 Markdown 保留主要邮件信息 | 导出选择损失+D，可恢复但需顺序/去重合同 |
| DOI、期刊信息 | 原图/Native 存在 | DOI 属 footer，不是 page_footnote；期刊文字属 header；未进 MD 主文本，部分品牌图像仍保留 | Marker 保存 DOI，不保证完整页眉/品牌文字 | 同样的选择损失，但不能用“只收 page_footnote”解决所有信息 |

正确保留：论文标题、五个机构的主要名称、ARTICLE INFO 日期/关键词、摘要主体、Introduction、主要左右栏续接。标题/正文分离较清晰；表格行列/单元格质量这两页未覆盖，双方 tables 为零，不能声称已验证。

## 5. 脚注为何消失：具体代码链

### MinerU 3.4.5 原生结构

安装目录 `runtimes/mineru/.venv/lib/python3.12/site-packages/mineru/backend/pipeline/`：

- `pipeline_magic_model.py:200` 附近将 HEADER、FOOTER、PAGE_NUMBER、ASIDE_TEXT、PAGE_FOOTNOTE 归入 discarded_blocks。
- `pipeline_middle_json_mkcontent.py:968` 附近 `union_make`：MM_MD/NLP_MD 仅 `make_blocks_to_markdown(paras_of_layout, ...)`；CONTENT_LIST/CONTENT_LIST_V2 则合并 layout 与 discarded。
- p43 的 4 个 page_footnote bbox 大致覆盖左栏 y588–706；p44 的 3 个覆盖左栏 y681–718。原始 index 不保证几何顺序：p44 双星通讯脚注 index27 在上方单星脚注 index28 之前，不能直接按 index 拼接。

### PDFFast 适配边界

- `pdffast/providers/mineru.py` WORKER_CODE 调用 do_parse，收集 content_list_v2/content_list/middle 为 raw_refs，选生成 Markdown 作为 markdown_path。
- `pdffast/providers/workers.py:581` 读取该 Markdown 为 RawProviderResult payload text，raw_refs 保留作 provenance/旁路。
- `pdffast/providers/normalization.py:1161–1175`：normalize_mineru 仅从 result.text 获得 raw_markdown，提取显式表格、公式、reading_blocks，markdown_to_plain_text 转为文本。
- `markdown_to_plain_text` 保留公式 body、链接标签，去除图片空 alt、Markdown 展示标记及 HTML 标签；本次遗漏脚注不在其输入中，故不是上述过滤造成。

### 能否恢复、会影响什么

可以不重新推理而恢复已有脚注，但必须先确立结构化输入与输出规则。作者/参考文献若被 Provider 分类为 discarded，同样可能受影响；本次作者标记却在普通 para span 就已缺，不能靠恢复 discarded 修复。公式识别错误也不能由脚注恢复修好。页眉/页码通常是有意排除内容，不能全部当正文收回。

直接追加全部 raw 风险：与既有段落或图像 alt 重复、同一区域不同表示重复、跨双栏插入顺序错误、标题/页眉误当正文、原始 bbox 坐标系误用、未知 block 类型/嵌套结构。当前 Markdown reading_blocks 本身不提供这些原生空间关系。

建议后续最小设计：在 RawProviderResult 的现有对象载荷中显式携带可识别的 supplemental blocks；Normalizer 只针对明确类型生成补充 reading evidence，保留 page/bbox/provider/provenance，精确去重和显式未知相对顺序。先离线试验 page_footnote，不把所有 discarded 加入正文、不新增“刚写再读”Runtime File Bus。该输入扩展与内容行为需先确认，本轮未实现。

## 6. Acceptance 当前职责与盲区

`pdffast/fallback/executor.py:46` 的 `_evaluate` 实际只检查：

| 条件 | 拒绝原因 |
|---|---|
| 非 SUCCESS/SUCCESS_WITH_WARNINGS | PROVIDER_EXECUTION_ERROR |
| output_contract.required 含 text，但 availability 非 AVAILABLE | TEXT_CHANNEL_UNAVAILABLE |
| empty_text_requires_warning=true，text.content 空白 | EMPTY_TEXT_WHEN_REQUIRED |
| required_structure_channels_any 均无 AVAILABLE 非空 items | REQUIRED_STRUCTURE_CHANNEL_UNAVAILABLE |

它不是仅用 SUCCESS 判定：还检查文本与任务要求的结构。但它是**能力/输出可用性合同**，没有完整性和语义真实性检查。两页 reading_blocks 10/16、文本非空，均满足要求，本轮重新调用结果确实 `(True, [])`。

未用指标：与 Native 字词覆盖、layout区域覆盖、discarded 内容价值、公式可解析性/冲突、人名准确率、重复率、参考文献/脚注保留、OCR置信分布。Normalizer 自身保留 raw Markdown/provenance，并不等于接受逻辑消费了这些信号。

## 7. Canonical/Renderer 对风险的放大边界

`pdffast/canonical/_stage10_builder.py:453–506`：LAYOUT_FALLBACK_REQUIRED 的 PAGE_FALLBACK 被设为 AUTHORITATIVE_PAGE_LAYOUT_FALLBACK；Native records 保留为 provenance，但单页独占记录标记 SUPPRESS_NATIVE_USE_PAGE_LAYOUT_FALLBACK。这与保守 region/inline overlay 不同。

因此已有 Native 正确词句不意味着最终正文一定补回；整页接受结果成为权威页面内容。历史两页使用 Marker，最终 Markdown 实际包含缺失句段、主要邮件及 nano-TiO 下标。新 MinerU 未构建完整 Canonical：其最终遗漏只能由代码推断为风险，不能冒称已观察到新的 C 类渲染缺陷。

## 8. 可复用的质量方案（仅设计，不修改策略）

| 风险信号 | 可以自动检查什么 | 不能据此断言什么 |
|---|---|---|
| Native 对齐覆盖 | 局部高可信 Native 字词在 recovered 中缺失；按空间区域/类别计算，对水印、页眉、断词和双栏作豁免 | Native 不是真值；不能用全页长度比直接判错或拼回 |
| 原始块 → normalized accounting | 明确类型块未被表示、公式/脚注未映射，记录 omission reason 与数量/空间范围 | 不能要求保留全部页码/重复页眉 |
| 内容结构冲突 | 上下标、作者机构标记、数值/单位/公式在两路证据中有冲突 | 无法自动证明哪个模型正确 |
| 公式异常 | LaTeX括号/命令错误、空公式、异常编码、检测区域有内容但无输出 | 语法正确的错误公式仍可能通过；Gamma/电荷正确性不能只靠语法 |
| 重复/顺序 | 相同 text+bbox/source 重复、跨栏关系不明、同块多次输出 | 无 bbox 时不能从字符串排除合理重复 |
| 检测/OCR置信度 | 已有 span 分数分布与低置信区域 | 模型可能高置信错误；本次漏句不保证有低分信号 |

分层建议：先增加离线 evidence accounting 与 warning/评估报表，再在人工标注样本上校准是否应拒绝/保留 Native/显式 unresolved。不要硬编码 case_003，不提高最低字数代替覆盖度，不将复杂页一律升级 Marker。生产 Acceptance 保持原样，本轮未降低门槛。

自动“发现分歧”与自动“修正事实”不同：人名、专业术语、公式语义、负电荷、作者归属关系需要可信来源或人工确认；无标准答案时不能保证准确。Marker 的 URL遗漏、阅读顺序取舍说明多 Provider一致/更长也不是事实保证。

## 9. 下一轮验证建议及性能影响

1. **无需模型重跑的脚注表示实验**：冻结本次 raw，在独立目录用对象输入处理 p43四/p44三 page_footnote；分别验证内容覆盖、原 page/bbox、已存在脚注不重复、上下顺序与未知类型跳过/告警。对原始 Marker/MinerU Markdown-only 接口做兼容测试，再测 Canonical/Markdown合同和新增内容行为。不直接改生产接受条件。
2. **Native/Recovered 离线覆盖实验**：两页按原 bbox和真实原文标注缺句、姓名、符号；将 Native 双栏交错、水印、cid编码作为负样本。测风险检测 precision/recall，而非为两页量身设拒绝阈值。
3. **扩大质量样本前确认**：另选真实表格、无 Native 文本、正常页眉脚注样本，先计划后批准；本轮不开展批量性能测试。

已测 MinerU execute 14.28/14.30秒明显低于历史 Marker 122.07/118.22秒，但质量不足不能叫无损收益。脚注恢复只能解决选择损失，不能恢复本次已错误的 OCR/公式；依赖修复后原链可能直接接受 MinerU并不再升级 Marker，故性能决策必须纳入整页权威替换的内容风险。

## 10. 修改与实际测试

本轮只新增此报告和 `outputs/case003_quality_acceptance_diagnosis/trace.json`；未修改 Normalizer、Acceptance、Provider、Canonical、HTTP合同或既有产物，未清理工作区、未提交 Git、未修改 v2/JudgeAI。

相关实际测试，含 reference-bound Normalizer parity：**34 passed，0 failed，0 skipped，0.89秒**。

```bash
PYTHONPATH="$PWD" PDFFAST_REFERENCE_ROOT=/Users/admin/Workspace/pdffast \
PYTHONDONTWRITEBYTECODE=1 /Users/admin/Workspace/pdffast-v2/.venv/bin/python -m pytest -q \
 tests/unit/test_runtime_normalization.py \
 tests/unit/test_raw_provider_normalizer_handoff.py \
 tests/unit/test_fallback_executor.py \
 tests/regression/test_prediction_normalizer_parity.py -p no:cacheprovider
```

仅借用现有解释器读取 v3源码；不写 v2、不生成字节码/pytest cache。原图查看、原 PDF pypdfium2读取、raw逐块检查与两次原 `_evaluate` 复算均已完成。未执行完整 full/reference套件，不把既有冻结数字当本次结果。由于未修生产 Normalizer，未宣称新增的脚注恢复、顺序/去重或HTTP端到端测试已通过。

完成后停止，等待确认是否进行脚注对象表示与覆盖度实验。
