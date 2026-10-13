# case_003 修复 MinerU 后已有解析结果核验

## 1. 结论

目标运行 `api_02845d6b80d1413db8963c36c26926b5` 已完成，原生日志真实总耗时 **226.776 秒（约226.8秒）**。54项增强任务终态闭合：52接受、2源区域保留unresolved、0 pipeline failure。最终Audit PASS/0 warnings，但不证明内容逐字正确。

性能显著改善：历史880.489秒减至226.776秒；绝对减少653.713秒，约74.24%。主要变化是7项原MinerU环境失败后交给Marker的整页任务，现在由MinerU成功接受。但 **43/44页最终内容仍有姓名、缺句、科学公式、机构关联和脚注缺失**；历史Marker在已核实的这些位置更接近原图。不能把速度改善描述为内容质量全面改善。

建议：日志优化可以作为独立提交候选；本case的运行可靠性与补充证据通道可以通过验收。**不能通过“与历史内容质量等价”或“JudgeAI关键材料信息完整”的验收**。允许下一阶段继续隔离质量验证；正式业务依赖附件作者、机构、公式/研究成果证据时，应先明确风险处理和人工核验，不自动调整路由或接受策略。

本轮只读已有结果和原PDF，生成此报告；没有模型调用、生产修改、8010重启、JudgeAI修改或Git操作。

## 2. Git收尾：独立提交范围（仅计划）

分支实际为refactor/v3；当前暂存区为空；git diff --check通过。此前两提交923d035、b075e25之外，本次正式日志优化依赖闭合范围为：

1. pdffast/runtime.py
2. pdffast/runtime_format.py
3. pdffast/providers/mineru.py
4. pdffast/providers/worker_logging.py（新增，必须与MinerU import一起）
5. pdffast/service/__main__.py
6. tests/unit/test_runtime_chinese_format.py
7. tests/unit/test_runtime_observation.py
8. tests/unit/test_runtime_log_modes.py（新增）
9. docs/reviews/runtime-log-noise-reduction.md（新增）

可作为一个独立日志优化提交，配套验证已实际完成：专项124 passed、full453 passed/20 skipped、reference473 passed，0 failed。此为上一轮实际验证结果，不是本轮重新执行数字。

明确排除并保留：

- JudgeAI集成：tools/acceptance/ 下4个工具，docs/reviews/judgeai-http-integration-acceptance.md；独立验收工具/报告，不混入日志实现。
- 离线实验：experiments/case003_quality/{offline.py,run.py,test_offline.py}；独立原型，当前不自动提交。
- :memory:.ses：来源待单独确认，不加入正式提交、不删除。
- outputs/ 下既有运行、模型输出、探针数据与大文件：只作为取证来源，不加入Git。
- 本报告：可以后续作为独立质量核验文档提交，不作为日志实现依赖。

本轮不执行任何暂存、提交、清理、push。

## 3. 输入身份、状态和产物完整性

运行目录 `outputs/service/api_02845d6b80d1413db8963c36c26926b5/`。manifest记录随机上传文件名d3cc410ef5ff493fbc93240dba97d663.pdf，内部source_file=input.pdf，66页。原上传PDF已经不在运行目录；**未找到此次上传文件本体SHA256记录，不能声称已验证上传字节指纹**。

当前参考PDF `/Users/admin/Workspace/pdffast/benchmark/samples/real/case_003.pdf` 的SHA256：`4769d5180d5e54f8e0d7bbac81f01bcb184dd428adbd2aac4bc20007c755328c`。

身份的实际强证据：

- 全量page_snapshot.jsonl与此前明确case_003历史run `api_c20df2b1a1e345439edbf6070a671859` 字节相同。
- TextFlow records全量与历史相等；原生文本、表格和顺序底座未变化。
- 43/44任务输入PNG与历史对应任务字节相同，SHA256分别为 `b51e100c2695cae7c3d78c3932b026264fb2f5fc6e4f26b7a36a6f06db82d138`、`77a9ef453e01c1f3d832176d6c4b768f3839f1dfee539ec98f672d189013b882`。
- 实际打开参考PDF的43/44页原图核对标题、作者、正文及脚注，与任务内容一致。物理页43/44的印刷页码是42/65、43/65，不混用。

据此确认属于case_003相同内容观察/任务输入；上传PDF二进制身份的证据缺口单独保留。

Production Manifest.status=COMPLETED；pipeline.log最后parse_finished，completed_tasks=54/54，无parse_failed终止。开始2026-10-09 17:35:22.484、结束17:39:09.258（北京时间）。用户提供HTTP200；本轮没有留存HTTP响应本体或再次HTTP调用，独立确认的是本地解析完成状态。

| 最终产物 | 实际状态 |
|---|---|
| result/document.md | 142035字节，101549字符，非空完整可读 |
| result/document.json | 17280069字节，合法JSON、schema1.1、66页 |
| result/audit.json | 26363字节，PASS，validation.pass=true，errors/warnings均空 |
| result/manifest.json | 526字节，run_id与以上路径匹配 |
| selected index/predictions | 54个index条目，54个目标JSON全部存在可解析 |
| Canonical inputs hashes | native_flow/Quality/provider_plan/selected_index四项SHA256均匹配实际文件 |

Canonical原生631条记录：510 paragraph、81 image_ref、39 table_ref、1 vector_ref；Audit changed_stage6_base_record_count=0。文件完整与内容正确是不同判断。

## 4. Provider结果与拒绝原因

| Provider | 尝试 | SUCCESS | FAILED | 接受 | 拒绝 | 最终被选择 | task窗口合计秒 | normalized elapsed合计秒 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| MinerU | 7 | 7 | 0 | 7 | 0 | 7 | 103.511 | 103.430 |
| RapidOCR | 47 | 47 | 0 | 44 | 3 | 44 | 45.643 | 42.971 |
| Marker | 3 | 3 | 0 | 0 | 3 | 0 | 27.943 | 27.909 |
| PaddleOCR文本 | 1 | 1 | 0 | 1 | 0 | 1 | 0.380 | 字段0，不能当作无推理耗时 |
| 合计 | 58 | 58 | 0 | 52 | 6 | 52 | 177.478 | 不作为墙钟总时间 |

6次拒绝全部EMPTY_TEXT_WHEN_REQUIRED，均执行SUCCESS但结果未接受。4个任务发生升级；无接受后继续高成本Provider的证据。p25/p32两区域RapidOCR和Marker均空，最终PRESERVE_SOURCE_REGION_UNRESOLVED；p42 INLINE的Marker空→RapidOCR接受；p57 REGION RapidOCR空→PaddleOCR接受。Docling与PaddleOCR-VL本次没有尝试，不能说全部六Provider已验证。

## 5. 43/44页：实际质量对照

依据：原PDF渲染原图；当前provider_raw JSON（含Markdown文本和SupplementalEvidence）、selected_predictions、Canonical fallback_overlays、最终document.md；历史相同任务的selected prediction及此前归档Marker文本；前轮case003-quality-acceptance-diagnosis.md。不预设Marker全部正确。

| 页/问题 | 原图与Native证据 | 本次MinerU及最终正文 | 历史Marker对应 | 判断 |
|---|---|---|---|---|
| 43 作者Chengang Dong | 原图明确，Native有正确姓名 | raw/normalized为hengang Dong，最终MD可见同错词 | 保留Chengang Dong | 原识别错误仍存在，最终权威页延续；不是脚注Normalizer丢字 |
| 43 Introduction缺句 | 原图“The development ... sources is of important scientific and technical interest for a large variety of applications” | “HE development ... generation a large variety ...”；scientific and technical句段不在本次页结果，最终MD同缺 | 对应句段存在 | 实质正文缺失，不只是空格或格式 |
| 43 数量级公式 | 原图10^8 cm/s | normalized含1\dot{0}^8异常形式，MD可见对应错误 | 历史更接近10^8，仍需逐公式核验 | 科学内容风险，不自动修正 |
| 43 作者单位/邮箱/基金/DOI脚注 | 原图有4块；Native存在相应字串 | Supplemental保留4块，未进入权威页text/MD；全文其他位置有xuming邮箱不能证明此页脚注保留 | 主要邮箱、基金及DOI可见，局部顺序也未保证完美 | 可追踪证据保留改善，但最终可读信息未恢复 |
| 44 作者机构标记 | 原图Qungui Wang上标b、cCollege of Science | 作者b与机构前缀c在raw/normalized缺失，最终MD延续 | 对应标记保留 | 影响作者与机构关系，不能根据位置自动猜 |
| 44 nano-TiO₂ | 原图可读，Native有TiO2但双栏/编码不完全可靠 | 特定nano公式为\mathbf{\cdot}\Gamma\mathbf{i}0_2，最终MD存在该错式；其他段落TiO仍存在不抵消该处错误 | 对应nano-TiO2更接近原图 | 模型识别错误，不由补充脚注修复 |
| 44 I₃⁻ | 原图明确负电荷；Native局部含异常编码 | raw/normalized为I3，最终MD同缺电荷 | 有I_3^- | 公式语义风险，Native也不能单独当真值 |
| 44 通讯作者/邮箱 | 原图单星、双星和邮箱3块 | 补充对象保留3块；该页text无邮箱，最终MD也没有liuqian@xaut.edu.cn、jinglinliujms@yeah.net | 邮箱/主要通讯信息保留 | 有价值信息仍不进入JudgeAI材料 |
| 44 DOI/期刊装饰 | DOI原图位于footer而非footnote | page_footnote机制不默认接收footer/header | Marker保留部分DOI | 本机制刻意分类，不应把所有discarded拼正文 |

正确保留的范围：两论文题名、摘要主体、主要左右栏段落及Introduction仍存在；44页主要机构名称、日期与关键词保留。未对全部66页逐字标注，不能报告总体precision/recall，也不能宣称全部表格/论文内容等价。

这两页的PAGE_FALLBACK render_policy均为AUTHORITATIVE_PAGE_LAYOUT_FALLBACK；原生记录stage10_resolution标记SUPPRESS_NATIVE_USE_PAGE_LAYOUT_FALLBACK。故正确Native文字留在Canonical provenance不意味着最终MD会补回。此次有实际最终MD，之前“可能丢失”的风险在上述位置已经观察到。

## 6. Supplemental Evidence及诊断

MinerU七页capture_status全部COMPLETE、callback_count均1；COMPLETE只表示捕获按合同完成，不证明OCR正确。

| 物理页 | raw块数 | 保留脚注 | 去重数 | 空间/顺序 |
|---|---:|---:|---:|---|
| 34 | 2 | 0 | 0 | 无脚注；空间/顺序统计None |
| 35 | 4 | 0 | 0 | 同上 |
| 43 | 8 | 4 | 0 | bbox完整；局部候选/正文关系UNRESOLVED |
| 44 | 12 | 3 | 0 | 同上 |
| 49 | 7 | 0 | 0 | 无脚注；不是捕获失败 |
| 51 | 9 | 4 | 0 | bbox完整；正文关系UNRESOLVED |
| 59 | 5 | 0 | 0 | 无脚注 |

合计11块脚注对象保留在RawProviderResult序列化JSON、selected prediction及Production Manifest摘要中。43页4个、44页3个完整文本都不在该页权威text，完整脚注段也不在最终MD。对象标记SUPPLEMENTAL_ONLY，page/bbox/pdf_point/mineru_page坐标系、原block index/source locator、Provider ID与局部顺序群组存在。44页原index的双星块在单星块之前；几何候选与原index独立，不猜正文插入位置。

### 诊断产物保留缺口

本run MinerU原生raw_refs共28个，24个不存在（最后p59的4个仍在）；43/44各4个Worker原生md/content_list_v2/content_list/middle文件均已不存在。源码mineru.py的Worker每任务删除共享output_dir/mineru_output再写出，任务build_command沿用输入父目录，后续页覆盖了该目录；这是可见代码与现存路径的证据，不是本轮清理。

因此最终结果与对象证据完整，但 **原生模型旁路refs不完整**。两页raw JSON仍含Markdown原文和supplemental blocks；上一轮冻结实验middle仍可对照，但不能将其冒充本次middle逐字输出。影响重放/详细质量归因，不影响已经完成的对象传递；本轮不改Worker或Artifact路径。建议独立确认后续是否保留任务级原生诊断目录。

## 7. DocumentUnit和章节

Canonical有5个RECOVERED文档anchor：p27合同、p29合同、p30结题审查通知、p36科技合作协议、p66成果登记表。角色全UNKNOWN；27/30/36范围PARTIAL，29/66范围RESOLVED；当前范围均单页，不把PARTIAL理解为整份附属文件范围已确认。没有凭Native来源自动生成Primary/section parent。

sections字段是66页的分组集合（多页section合并后共60组），16个有标题分组，其余明确None；主要一至九章、附件清单/材料目录等来自观测标题。重复“资助批准通知”对应19/20/24页不同证据，不仅凭文字相同合并。43/44页section_title=None，论文题名来自layout fallback正文，不冒充新Section；页与region来源可追踪，但论文之间的正式文档/章节关系未完备。

这里只确认输出不把未知parent当确定关系，并核对43/44实际原图；未对所有anchor边界人工验真。五个DocumentUnit不能解释为整个66页已完整分成五份文档。

## 8. 性能对照与局限

| 范围 | 本次秒 | 历史秒 |
|---|---:|---:|
| Native全窗口 | 14.367 | 14.723 |
| Evidence | 5.137 | 4.506 |
| Quality | 2.744 | 2.696 |
| Fallback planning | 6.181 | 5.976 |
| Provider execution全窗口 | 196.824 | 850.727 |
| Canonical | 1.084 | 1.413 |
| Renderer | 0.015 | 0.018 |
| Audit | 0.016 | 0.023 |
| 总墙钟 | 226.776 | 880.489 |

表为部分阶段，不能把这些行当作完整分解相加。完整起止事件保存在pipeline.log；总时长取parse_finished.elapsed_seconds。任务窗口配对58对、串行无重叠，总177.478秒；四Provider初始化/preflight/READY合计13.139秒；Provider剩余约6.207秒是未细分间隙/清理/写出等，不能全部命名为Normalizer。

| 关键任务 | 历史执行情况 | 本次 |
|---|---|---|
| p43 PAGE | MinerU依赖失败→Marker122.065秒接受 | MinerU task16.601秒接受，worker elapsed16.588 |
| p44 PAGE | MinerU依赖失败→Marker118.217秒接受 | MinerU task18.297秒接受，worker elapsed18.282 |
| p42 INLINE | Marker120.268秒空→RapidOCR | Marker24.083秒空→RapidOCR |
| p34 PAGE | MinerU失败→Marker35.118秒接受 | MinerU task23.407秒接受 |

Marker尝试10→3、接受7→0，MinerU7次失败→7次成功/接受，总尝试65→58；RapidOCR47次/44接受、Paddle1次/1接受以及终端保留2项没有变化。7个layout页34/35/43/44/49/51/59改变最终Provider；不能据此断言7页内容都更好。Markdown100904→101549字符，增加645字符不是完整性证明。

MinerU初始化窗口9.498、Marker0.129、RapidOCR0.747、Paddle2.765秒；READY不一定含全部模型加载，task窗口包括推理/Normalizer/Acceptance和外围I/O。没有独立Normalizer timer。本次七个Worker响应有实际推理参数，但没有完整CPU负载、缓存状态、依赖/model checksum和统一环境快照。p42同Marker变快、初始化也变化，说明不能把653.713秒全部归功于“换为MinerU”，更不能承诺稳定3.88倍普遍加速。

## 9. JudgeAI影响与下一阶段条件

当前JudgeAI Adapter保存Canonical完整对象但主要材料上下文是Markdown。SupplementalOnly和Native provenance中保留的信息，**不会自动进入模型材料**。因此43/44附件作者关系、通讯信息、技术公式和实质正文缺句可能影响材料理解、成果归属或技术内容判断；尚未运行AI评审，不声称已证明评分变化。

有利证据：主申报结构和Native TextFlow底座与历史相同；HTTP1.0/Canonical1.1外层输出存在，54任务终态闭合，Audit invariant无异常。限制：仅有限页内容人工核验；payload约17.28MB，实际JudgeAI case_003接收/上下文开销未在本轮测量；原生raw_refs回放缺口；文档关系/脚注关系未知。

下一阶段最小建议（只提出，不实现）：

1. 对43/44和其余5个切换页建立有限人工标注对照，分开正文遗漏、作者标记、公式和表格，不用全页长度阈值替代。
2. 评估脚注独立附属信息的安全展示合同，仍不直接拼进正文；保留来源/未知关系。
3. 将Native/Recovered覆盖风险检测继续作为诊断实验，不硬编码case姓名、不直接改变Acceptance或全升级Marker。
4. 单独处理原生Worker诊断目录持久化问题；先确定兼容影响和必要保留策略。
5. JudgeAI隔离验收使用本次MD人工核验后的材料，明确人工复核/质量风险政策后再批准正式业务验收。

## 10. 本轮验证与任务逐项清单

本轮没有代码/模型执行，不重跑pytest；实际执行Git状态/分支/暂存/diff检查、JSON解析/引用哈希检查、任务与事件统计、已有结果对照以及两页原PDF渲染查看。先前日志专项/回归数字仅作为提交候选依据。

以下54条完整终态及所有拒绝原因取自本run selected_predictions，与Manifest计数一致：

| task_id | page | 类型 | 最终Provider | 终态 | 尝试未接受原因 |
|---|---:|---|---|---|---|
| s9_0001_region_fallback_9a73f2aff22a | 1 | REGION_FALLBACK | rapidocr_ch_light | 接受 | — |
| s9_0021_page_fallback_442cdbc188b8 | 21 | PAGE_FALLBACK | rapidocr_ch_light | 接受 | — |
| s9_0022_page_fallback_913012a2a737 | 22 | PAGE_FALLBACK | rapidocr_ch_light | 接受 | — |
| s9_0023_page_fallback_c327a886fa79 | 23 | PAGE_FALLBACK | rapidocr_ch_light | 接受 | — |
| s9_0024_page_fallback_1b0ae3b8d6a4 | 24 | PAGE_FALLBACK | rapidocr_ch_light | 接受 | — |
| s9_0025_region_fallback_952a543c644f | 25 | REGION_FALLBACK | 无 | 源区域unresolved | rapidocr_ch_light:EMPTY_TEXT_WHEN_REQUIRED; marker_local:EMPTY_TEXT_WHEN_REQUIRED |
| s9_0025_region_fallback_ed40220a8498 | 25 | REGION_FALLBACK | rapidocr_ch_light | 接受 | — |
| s9_0026_page_fallback_4ab1758da51e | 26 | PAGE_FALLBACK | rapidocr_ch_light | 接受 | — |
| s9_0027_page_fallback_0260f9ae5126 | 27 | PAGE_FALLBACK | rapidocr_ch_light | 接受 | — |
| s9_0028_region_fallback_38125d656750 | 28 | REGION_FALLBACK | rapidocr_ch_light | 接受 | — |
| s9_0029_page_fallback_9ca6452f49a8 | 29 | PAGE_FALLBACK | rapidocr_ch_light | 接受 | — |
| s9_0030_page_fallback_9ea797c3cdd5 | 30 | PAGE_FALLBACK | rapidocr_ch_light | 接受 | — |
| s9_0031_page_fallback_a62a1443f09e | 31 | PAGE_FALLBACK | rapidocr_ch_light | 接受 | — |
| s9_0032_region_fallback_0de3317b1a02 | 32 | REGION_FALLBACK | rapidocr_ch_light | 接受 | — |
| s9_0032_region_fallback_8e9dbdb62544 | 32 | REGION_FALLBACK | 无 | 源区域unresolved | rapidocr_ch_light:EMPTY_TEXT_WHEN_REQUIRED; marker_local:EMPTY_TEXT_WHEN_REQUIRED |
| s9_0032_region_fallback_92a51e1c24e6 | 32 | REGION_FALLBACK | rapidocr_ch_light | 接受 | — |
| s9_0034_page_fallback_32afc416c678 | 34 | PAGE_FALLBACK | mineru_local | 接受 | — |
| s9_0035_page_fallback_74073a75896d | 35 | PAGE_FALLBACK | mineru_local | 接受 | — |
| s9_0036_page_fallback_e2a7405350fc | 36 | PAGE_FALLBACK | rapidocr_ch_light | 接受 | — |
| s9_0037_page_fallback_6dbaf5fed037 | 37 | PAGE_FALLBACK | rapidocr_ch_light | 接受 | — |
| s9_0038_page_fallback_09786497f5bd | 38 | PAGE_FALLBACK | rapidocr_ch_light | 接受 | — |
| s9_0039_page_fallback_976a4c66dce5 | 39 | PAGE_FALLBACK | rapidocr_ch_light | 接受 | — |
| s9_0040_page_fallback_57df73534166 | 40 | PAGE_FALLBACK | rapidocr_ch_light | 接受 | — |
| s9_0041_page_fallback_4f9e4f69de66 | 41 | PAGE_FALLBACK | rapidocr_ch_light | 接受 | — |
| s9_0042_inline_context_fallback_7ae8402f600c | 42 | INLINE_CONTEXT_FALLBACK | rapidocr_ch_light | 接受 | marker_local:EMPTY_TEXT_WHEN_REQUIRED |
| s9_0042_region_fallback_d4027e6c00c7 | 42 | REGION_FALLBACK | rapidocr_ch_light | 接受 | — |
| s9_0043_page_fallback_5aba61185609 | 43 | PAGE_FALLBACK | mineru_local | 接受 | — |
| s9_0044_page_fallback_4fedefb0cbce | 44 | PAGE_FALLBACK | mineru_local | 接受 | — |
| s9_0045_region_fallback_a530856a38ef | 45 | REGION_FALLBACK | rapidocr_ch_light | 接受 | — |
| s9_0046_region_fallback_bdab1fd5317f | 46 | REGION_FALLBACK | rapidocr_ch_light | 接受 | — |
| s9_0047_region_fallback_048fe36445ac | 47 | REGION_FALLBACK | rapidocr_ch_light | 接受 | — |
| s9_0047_region_fallback_32877e07b55c | 47 | REGION_FALLBACK | rapidocr_ch_light | 接受 | — |
| s9_0048_region_fallback_1b0a6661dfe8 | 48 | REGION_FALLBACK | rapidocr_ch_light | 接受 | — |
| s9_0049_page_fallback_9c2b39d10fa8 | 49 | PAGE_FALLBACK | mineru_local | 接受 | — |
| s9_0051_page_fallback_68670adee3aa | 51 | PAGE_FALLBACK | mineru_local | 接受 | — |
| s9_0052_region_fallback_457b9723dd1b | 52 | REGION_FALLBACK | rapidocr_ch_light | 接受 | — |
| s9_0052_region_fallback_5489f13af876 | 52 | REGION_FALLBACK | rapidocr_ch_light | 接受 | — |
| s9_0053_page_fallback_73ac97490afa | 53 | PAGE_FALLBACK | rapidocr_ch_light | 接受 | — |
| s9_0054_page_fallback_4208e115439f | 54 | PAGE_FALLBACK | rapidocr_ch_light | 接受 | — |
| s9_0055_page_fallback_9af0e7a8f591 | 55 | PAGE_FALLBACK | rapidocr_ch_light | 接受 | — |
| s9_0056_page_fallback_fa1a0153c522 | 56 | PAGE_FALLBACK | rapidocr_ch_light | 接受 | — |
| s9_0057_region_fallback_2a61bf512bce | 57 | REGION_FALLBACK | paddleocr_v5_mobile | 接受 | rapidocr_ch_light:EMPTY_TEXT_WHEN_REQUIRED |
| s9_0057_region_fallback_724495a14c59 | 57 | REGION_FALLBACK | rapidocr_ch_light | 接受 | — |
| s9_0059_page_fallback_72b055c260ca | 59 | PAGE_FALLBACK | mineru_local | 接受 | — |
| s9_0060_page_fallback_aebd76de4ce5 | 60 | PAGE_FALLBACK | rapidocr_ch_light | 接受 | — |
| s9_0061_page_fallback_e7a57997b89e | 61 | PAGE_FALLBACK | rapidocr_ch_light | 接受 | — |
| s9_0062_page_fallback_08283a17000a | 62 | PAGE_FALLBACK | rapidocr_ch_light | 接受 | — |
| s9_0063_region_fallback_11a8bc2b41a6 | 63 | REGION_FALLBACK | rapidocr_ch_light | 接受 | — |
| s9_0063_region_fallback_65b82809d73c | 63 | REGION_FALLBACK | rapidocr_ch_light | 接受 | — |
| s9_0064_page_fallback_c08f22891e19 | 64 | PAGE_FALLBACK | rapidocr_ch_light | 接受 | — |
| s9_0065_region_fallback_615125254074 | 65 | REGION_FALLBACK | rapidocr_ch_light | 接受 | — |
| s9_0065_region_fallback_9ff6a79b4111 | 65 | REGION_FALLBACK | rapidocr_ch_light | 接受 | — |
| s9_0065_region_fallback_a06dbfee31d3 | 65 | REGION_FALLBACK | rapidocr_ch_light | 接受 | — |
| s9_0066_page_fallback_7fd06c196caf | 66 | PAGE_FALLBACK | rapidocr_ch_light | 接受 | — |
