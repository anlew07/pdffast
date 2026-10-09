# Native / Recovered 内容覆盖风险离线实验 B

日期：2026-10-09。独立风险证据，不作为生产接受/拒绝条件。

## 输入与真实输出

依据：case003-quality-acceptance-diagnosis、mineru-case003-pages43-44-validation、case003-performance-diagnosis 三份报告。冻结产物与实验A相同；额外消费 Native page_snapshot 的 words及空间坐标、MinerU para_blocks/公式spans、normalized文本、历史归档Marker canonical文本。已有人眼原图核验来自前一轮报告，本轮未重新做全文人工转录。

输入绝对路径及hash：`outputs/case003_content_quality_experiments/input_manifest.json`。实际结果：`page_43_coverage_risks.json`、`page_44_coverage_risks.json`；每条保留 page、原始source/JSON pointer、文本/公式或bbox以及分类。

原型 `experiments/case003_quality/offline.py` 由独立驱动run.py执行。不读取生产 Runtime 文件，不接入 Acceptance，不改结果或公式，truth_selected=null、production_decision=null。

## 方法与分类

- 将 Native words 中心点从 PDF页面 width/height 缩放到 MinerU page_size；在 Provider块bbox内选 Native词，按局部top/x排序，再做 Unicode/空白/断词规范后的 SequenceMatcher对齐。
- 不比较全页长度，也不把双栏交错的 native_text串当真值。通过原生 words 空间范围降低全页错位影响。
- 长度≥3字符的编辑差异生成 REGION_TEXT_DISAGREEMENT；这是实验显示阈值，未经校准，不是生产质量阈值。
- 可识别cid/替换编码产生 UNASSESSABLE，不对错误编码做事实修正。公式spans无条件产生待复核证据，**不是判定每个公式有错**。
- 原始 page_footnote 有文本但normalized中未表示：CONFIRMED_LOSS，只证明表示层遗漏，不证明OCR每字正确。
- 完全相同块产生重复风险；多栏关系未建立时记录顺序风险。块外区域/未覆盖Native字的完整accounting尚未实现。

四类状态：CONFIRMED_LOSS（已证实表示损失）、EVIDENCE_CONFLICT（源间分歧）、RISK_UNVERIFIED（需核验风险）、UNASSESSABLE（现有证据/类型无法评价）。不会自动选Native/Marker当正确来源。

## 实际统计

| 证据类型 | p43 | p44 | 解释 |
|---|---:|---:|---|
| REGION_TEXT_DISAGREEMENT | 4 | 5 | 含真实问题及误报，不等于9项已证实模型错误 |
| FORMULA_REQUIRES_REVIEW | 2 | 3 | 所有5个原生公式span均列复核，未判定语义正确性 |
| RAW_FOOTNOTE_NOT_REPRESENTED | 4 | 3 | 7块raw存在而normalized缺失 |
| NATIVE_ENCODING | 0 | 2 | cid编码，不作Native真值 |
| BODY_RELATIVE_ORDER | 1 | 1 | 双栏/跨块顺序未确定 |
| 完全重复块告警 | 0 | 0 | 没检出不代表不存在局部重复 |

## 已发现、未发现和误报

| 已核验差异 | 实际原型表现 | 边界 |
|---|---|---|
| p43正文缺句 | bbox [34,417,291,574] 的 delete片段含 `sourcesisofimportantscientificandtechnicalinterestfor` | 成功指出空间对应缺失；需原图判定Native正确 |
| p43作者 Chengang→hengang | **漏检**；单字符编辑被≥3显示阈值排除，Native黏词也影响对齐 | 不能称人名检测已完成 |
| p43 10^8异常dot | 右栏区域插入dot分歧，原始公式span进入复核 | 不能自动证明dot不应存在；公式需原图 |
| p44机构标记b/c遗漏 | 作者bbox分歧仅见多个标记聚合；单个机构c可能漏检 | 未建立作者—机构/上标结构匹配 |
| p44 nano-TiO₂损坏 | 对应区域出现LaTeX命令/Gamma分歧，公式span复核 | 文本比较会将正常TeX表示也报差异，非可靠化学式错误判定 |
| p44 I₃⁻负电荷遗漏 | Native cid编码被标为无法评估；没有可靠专用电荷冲突检出 | **未自动验证/修复电荷** |
| 7脚注缺失 | CONFIRMED_LOSS均检出 | 表示缺失可证实；文字准确性仍需人工 |
| DOI/footer缺失 | 被排除普通正文规则，未单列价值告警 | **未覆盖**；需要单独出版信息分类 |
| 参考文献/真实表格关系 | 两页无足够对应样本 | 无法评估，不能外推 |

明确误报来源：

- p43 Native水印“版/式”混入单词，产生 investigate/repetition及引用编号差异；本原型只隔离cid编码，**尚未可靠剔除水印**。
- p44 ARTICLE INFO同一Provider块包含关键词而bbox仅覆盖部分日期，空间匹配Native缺词，产生虚假插入。
- p44 fluorescence被报告先删后加，来自Native局部词序与排版，不能当漏词。
- p44正文para合并左右栏但bbox主要为左栏，右栏后半段被当插入。表明para bbox并不总覆盖合并内容；未来应改用逐line/span几何并标记跨栏。
- 正常LaTeX命令、引文横线、Unicode符号差异也触发冲突；需要表示层规范与公式专属比较。

单字符过滤减少噪声却漏姓名首字母/机构标记；全页长度阈值不会解决。当前也没有高可信Native筛选器（字体、隐藏层、坐标、编码等），所以**不能把输出称为“高可信Native缺失判定”**。

## 负样本及测量范围

自动测试：全页双栏交错字符串不参与局部比较；Provider正文bbox外header不导致正文缺失；cid编码不判真值；断词脚注不会重复；未知类型安全跳过；公式冲突不产生corrected_text，Native与Recovered不同也不选真值。

这些是合成行为验证，不是已标注真实负样本集的准确率。真实页上的水印、块跨栏、TeX表示仍有上述误报。两页已有人工差异来自选择性抽查，未形成穷尽标注，不统计precision/recall；9条空间分歧不能作为9真阳性。没有全文字词/关系级金标准，不能外推普遍检测能力。

## 独立质量证据合同建议

建议在Acceptance之外保持独立 evidence report：category、classification、page/region、source_provider、source_ref、native/recovered片段、alignment method、reason、assessability、review_required。风险不直接变拒绝、不自动覆盖任一来源。

- accounting可说明原始块保留/排除原因，区分page_footnote与header/footer/reference/formula，不机械一套过滤。
- 新风险项需独立版本，明确证据不足和未评估范围；不承诺综合score代表真实质量。
- Marker支持Native区域只是辅助证据；其归档文本无该原型使用的空间匹配，不用于选真值。字符串compact可能受词序/TeX影响，支持缺失也不是Marker反证。
- 生产公共合同暂不需要改变；内部若接入需显式Native words/区域、raw结构化blocks和normalized对象输入，不能回读刚输出JSON。

## 建议下一轮及性能结论

先建立小型标注集：包含有/无Native、双栏合并、上标、化学式、脚注、出版信息、水印/隐藏层、公式正常/错误、表格及重复块。按缺陷和区域独立标注“事实/分歧/无法判断”，多人核验或记录不一致；再报告各类别precision/recall及样本量。

优先改进离线逐span几何及accounting，再评估高可信Native筛选和公式专门表示。单字符姓名/机构检测必须用结构化上下文且只报分歧，不能词典硬编码当前姓名。扩展实验不等于批准改生产Acceptance。

更快MinerU仍有质量问题；补脚注只能修表示损失，不能修已错误的姓名、正文与化学式。当前不足以据此调整路由或声称无损节省。

## 实际测试与范围

离线11项加既有Normalizer/object handoff/Executor/reference parity：**45 passed，0 failed，1.86秒**。未运行完整suite或模型。命令：

```bash
PYTHONPATH="$PWD" PDFFAST_REFERENCE_ROOT=/Users/admin/Workspace/pdffast \
PYTHONDONTWRITEBYTECODE=1 /Users/admin/Workspace/pdffast-v2/.venv/bin/python -m pytest -q \
 experiments/case003_quality/test_offline.py tests/unit/test_runtime_normalization.py \
 tests/unit/test_raw_provider_normalizer_handoff.py tests/unit/test_fallback_executor.py \
 tests/regression/test_prediction_normalizer_parity.py -p no:cacheprovider
```

真实fixture测试只依赖本机冻结产物，属于离线验收入口，未加入默认production测试集合；复用别人环境需要提供相同fixture，不声称可在空仓库直接运行。

本轮新增实验源码、测试、两份报告及独立结果目录；未改生产PDFFast、Router、Fallback、Acceptance、Canonical权威选择、HTTP、PDF算法、v2/JudgeAI，未提交/清理。

## 整合建议

1. 可进入下一轮实现设计：带来源/bbox/原始类型的**补充证据对象**和块记账，先不改变正文输出；生产接入仍需合同校验、空间去重和顺序测试。
2. 不宜直接上线：本次区域覆盖、姓名/公式风险判定；误报漏报明确，需要扩大标注并校准。
3. 只能warning：源间冲突、公式语义、相对顺序不确定、低证据可评估性；不转拒绝/自动修正。
4. 需扩展内部接口：Worker → RawProviderResult.payload.supplemental_blocks → Normalizer独立补充证据；Native区域对象 → 独立质量证据消费方。保持Markdown-only及HTTP合同。
5. 建议先批准补充证据合同与离线去重/顺序完善；**暂不进入Acceptance或Canonical实际行为修改**。本轮到此停止。
