# case_003 内容质量风险与解析证据闭环方案

## 1. 范围与结论

本轮只读取源码及已有产物；未运行 Provider、完整 PDF 或回归测试，未修改生产逻辑、JudgeAI、配置或测试。目标运行为 `api_02845d6b80d1413db8963c36c26926b5`，产物根目录为 `outputs/service/api_02845d6b80d1413db8963c36c26926b5`。

已有产物确认：总耗时 226.776 秒，54 个增强任务终态闭合，52 个接受、2 个 unresolved。HTTP 200、Acceptance 接受和 Audit PASS 均不能证明逐字正确。第 43、44 页仍有模型识别错误和遗漏；7 条脚注通过 SupplementalEvidence 保存，但按当前设计没有成为最终正文。

推荐先实施**证据闭环，不改变内容决策**：共同解析入口记录实际输入 SHA-256；明确 MinerU 原生输出的临时/持久化合同并保留有界取证材料。质量检测先扩大标注与负样本，不能把当前离线原型直接变成生产拒绝条件。

依据包括以下完整报告与当前源码、运行 JSON/Markdown：

- `case003-post-mineru-fix-validation.md`
- `case003-quality-acceptance-diagnosis.md`
- `native-recovered-coverage-experiment.md`
- `mineru-supplemental-blocks-experiment.md`
- `supplemental-evidence-contract.md`

## 2. 已确认问题与证据边界

| 问题 | 本次最早可观察环节 | 后续表现 | 结论 |
|---|---|---|---|
| p43 作者 Chengang Dong 被识别为 hengang Dong | MinerU raw 结果内的 Markdown | normalized、Canonical 权威页内容和最终 Markdown 延续错误 | 不是 Normalizer 把正确姓名删错；具体模型机制尚不能确定 |
| p43 Introduction 缺少 “sources is of important scientific and technical interest for” | raw Markdown 已缺失 | 最终正文仍缺句 | 模型/导出上游缺口，不能凭空补写 |
| p43 `10^8` 的识别异常 | raw Markdown 中出现 `1\\dot0^8` | 下游保留异常表达 | 不能仅靠 TeX 字符不同判定公式语义，但此项有 PDF 可见证据支持 |
| p44 nanoTiO2、I3 的公式/化学式表达错误或电荷遗漏 | raw Markdown | normalized 和最终正文延续 | 原始识别阶段已出现问题；Native 编码异常也限制自动交叉核验 |
| p44 作者、机构标记关系不完整 | raw Markdown | 无可靠下游关系可恢复 | 不应根据姓名或机构常识补全 |
| p43 4 条、p44 3 条脚注未进入正文 | MinerU Markdown 导出没有这些脚注；结构捕获对象有文本 | SupplementalEvidence 保留，Canonical/Markdown 未消费 | 不是捕获失败，也不是 Normalizer 丢弃收到的脚注正文 |
| 双栏、脚注与正文关系不确定 | 原始块和几何顺序之间有差异 | 保留 UNRESOLVED 和局部候选 | 几何候选顺序不等于语义阅读顺序 |

当前缺失的 MinerU middle/content_list 不能作为仍然可读取的本次原始证据引用。早期冻结实验的同页结构可以说明机制和已观察模式，但不能替代本次模型内部输出。对于缺句，当前 raw Markdown 足以定位“在 Normalizer 之前已缺失”，不足以区分模型未识别与模型结构到 Markdown 的导出遗漏。

来源 PDF 当前文件 SHA-256 为 `4769d5180d5e54f8e0d7bbac81f01bcb184dd428adbd2aac4bc20007c755328c`。本次 HTTP 上传没有保存自己的字节指纹，故不能声称已证明上传文件逐字节等于该参考文件。运行 snapshot、TextFlow 和 p43/p44 任务图像与历史产物的对应关系支持内容关联，但不代替上传字节证明。

## 3. HTTP 输入生命周期与指纹方案（P1）

### 当前真实路径

`pdffast/service/app.py:_parse_pdf_sync` 在 `TemporaryDirectory(prefix="pdffast_upload_")` 中通过 `shutil.copyfileobj` 保存 `input.pdf`，检查非空后调用 Parser。解析返回或异常展开后，临时目录清理，上传文件句柄在 finally 关闭。

`ParseService`、`PipelineContext` 和 runner 接收 PDF 路径，没有输入 PDF SHA-256 合同。Registry 的模型资源 SHA-256、Canonical 的 artifact/object 摘要、Normalizer 的 raw 摘要用途不同，不能复用其值作为输入指纹。JudgeAI 的 `backend/app/services/parse_result_service.py` 已有自身输入 PDF 哈希，但当前 PDFFast HTTP v1 没有返回与实际解析输入绑定的摘要。

删除上传临时文件是现有设计，不直接判为内容数据丢失；缺口是无法独立证明本次实际输入。

### 最小方案

在共同 `ParseService` 入口、Native 扫描前，对实际解析路径流式计算 SHA-256 和字节数，创建只读内部输入元数据；通过现有运行诊断/Manifest 持久化，最终 Manifest 复用同一元数据。应尽早保存，使失败运行也可追踪。记录字段建议：算法、digest、byte_size、run_id、原始展示文件名、采集状态及失败原因；不把临时绝对路径当稳定身份。

不扩展 ParseResult 或 HTTP v1，不把 Canonical 内部工具反向引入 application 层。HTTP 在复制时同时哈希是可选优化，但不是首版必要条件，也不能遗漏直接 Parser 调用。

边界：HTTP 私有输入通常固定；直接调用者可能在哈希后修改文件。首版需明确输入保持不变的前提，记录前后文件状态变化并告警；不能声称 stat 检查证明字节不变。需要严格快照保证时，再单独评估私有副本或解析后复核摘要的成本与行为。

指纹不能证明 OCR 正确，也不意味着必须永久保存全部原始 PDF。源文件留存、访问控制、隐私及保留期限应由存储政策决定。

## 4. MinerU 28 个引用与证据保留（P1）

### 缺失原因

`providers/workers.py:build_command` 默认以任务输入父目录作为 output_dir；本次同类 PAGE 输入共享父目录。`providers/mineru.py:WORKER_CODE` 每次 parse 都对 `output_dir/mineru_output` 执行存在检查、`shutil.rmtree` 和重建。

本次 7 个 MinerU 页面各有 4 个引用：Markdown、content_list_v2、content_list、middle JSON，共 28 个。p34、35、43、44、49、51 的 24 个引用已不存在；最后 p59 的 4 个仍存在。此模式与逐任务重建共享输出目录一致，是任务间 scratch 清理，不是已证实的服务 shutdown 删除或移动错误。

Worker 已把 Markdown 和捕获对象交给父进程，后续对象链不要求重新读取这些原生文件。因此这不是 Runtime File Bus 退化，也不能推断最终文本随临时目录一起消失。问题是持久化 raw_refs 没有明确标示其临时有效期，导致后续取证能力不足。

另一个需纳入设计的边界：现有 ArtifactPaths 的 raw_result 以 task_id 命名；同任务多 Provider attempt 可能覆盖此前 raw 文件。selected 包装保留各次 normalized attempt、接受原因及诊断，不代表所有原始输出均按 attempt 独立留存。

### 分类与有界保留

| 数据 | 当前/未来作用 | 推荐 |
|---|---|---|
| 输入摘要、任务输入身份、Production Manifest、各 attempt 决策与诊断 | 运行关联、决策复核 | 作为核心可追踪证据保留 |
| Native snapshot、normalized 内容、SupplementalEvidence | 内容与来源核验 | 现有旁路保存，避免重复大对象 |
| MinerU Markdown 与一个主要结构表示/有来源的精简投影 | 模型错误、导出损失、空间对齐取证 | 有界 allowlist 归档 |
| 重复 content_list/v2/middle 全量副本 | 兼容研究可能需要 | 不默认全部长期保存；指定主要表示和必要差异 |
| 模型权重、张量、全量调试图、重复原始 PDF | 临时推理/调试 | 不因证据闭环永久归档 |
| 被 Markdown 实际引用的图片 | 是否需要取决于最终引用合同 | 逐项检查可达性；不能留下最终文档失效引用 |

现有 Audit PASS 不需要全部 MinerU middle 文件；“结构取证需要”与“当前 Audit 必需”必须区分。

最小实现建议：复用 ArtifactPaths，按 run/provider/task/attempt 隔离临时输出与证据归档；在清理前保存允许的材料并记录类型、相对路径、hash、大小、来源、保留状态和原因。写完再公布可用记录，避免半写文件被当完整证据。生命周期状态用于表达临时、归档成功、归档失败、按政策过期，不重定义 supplemental capture_status。

设置单 attempt、单 run 和总存储预算及保留期限；具体数值需依据容量和隐私政策确认，不能本轮猜定。超额或归档失败明确记诊断，不能伪装为“该页无脚注”。过期删除应留下可解释的可用性记录。不要新增平行后台存储系统，也不把归档读取引入 fresh runtime。第一阶段不改变 Acceptance 或 PDF 成功条件。

## 5. 当前内容选择与风险边界

`fallback/executor.py:_evaluate` 主要检查 SUCCESS、所需文本通道可用且非空、所需结构通道可用且非空。它没有可靠的姓名、公式真实性或全文完整性判据。SUCCESS 与 accepted 是不同状态，accepted 又不是逐字质量证明。

`canonical/_stage10_builder.py` 在对应质量决策和 capability 条件下将 PAGE_FALLBACK 作为 OCR/layout 权威页；单页 Native 来源记录采用 `SUPPRESS_NATIVE_USE_PAGE_OCR_FALLBACK` 或 `SUPPRESS_NATIVE_USE_PAGE_LAYOUT_FALLBACK`。保留 Native provenance 不等于最终 Markdown 同时展示 Native 正确内容。p43/p44 的被接受 layout fallback 因此可能覆盖更准确的 Native 片段。

`providers/normalization.py:normalize_mineru` 接收 raw Markdown，supplemental 通过单独对象/metadata 通道保留；`compact_canonical` 的内容白名单未消费这些证据。脚注不进入最终正文是已批准的消费边界，不应通过拼接 discarded_blocks 修补。

p44 原始脚注 index 与局部几何候选不同；body_order 为 UNRESOLVED。不能把作者、机构、邮件、脚注编号和正文关系自动连成确定事实。

## 6. 最小质量防护候选方案

| 候选 | 可用证据与输出 | 误报风险 | 漏报/不可判断 | 推荐边界 |
|---|---|---|---|---|
| 块保留检查 | 同一次 raw 结构到 normalized 的来源身份/文本去向，输出已证实表示损失 | 有意不进入正文的页眉、脚注被误称丢失 | 原模型已漏掉的字不可发现 | 诊断，区分捕获、保存、展示 |
| Native/Recovered 局部覆盖 | 校准页码、bbox、单位、裁剪/旋转后按行/span 对齐，输出覆盖缺口 | 双栏串行、断词、编码、隐藏文本、水印、页眉 | 扫描页无 Native、单字缺失、几何错位 | 先离线扩大标注；缺证据输出不可评估 |
| 高可信来源冲突 | 多个独立来源同一区域存在差异，保留双方和置信依据 | 同源模型并非独立、合法不同表达 | 一致错误、无 confidence 字段 | 标冲突，不指定真值 |
| 姓名/作者标记风险 | 局部字符差异、上标关系与位置证据 | Native 连字、姓名断词 | 缺标准答案无法确认姓名正确 | 人工复核，不靠姓名词典补全 |
| 数字/公式/化学式风险 | 原图区域、Native span、模型公式结构之间可见冲突 | 合法 TeX 等价、编码差异 | 电荷/上下标 Native 也损坏 | 标风险，不自动改写 |
| 重复/顺序风险 | 来源身份、重叠区域、重复块和局部几何 | 不同区域合法相同内容 | 跨栏关系未知 | 不按纯文本去重，不猜跨栏顺序 |
| 补充证据覆盖摘要 | COMPLETE/失败/未执行、保留数、未展示原因 | 把 COMPLETE 当准确率 | 捕获外的模型遗漏 | 已有诊断复用，明确非正文 |

现有离线原型使用 Native 词中心与 MinerU block bbox、文本规范化和相似度。它发现 p43 缺句区域，但漏报姓名首字符差异；也有水印、Native 编码、跨栏段落 bbox 和正常公式表达带来的误报。尚无充分精标样本支持 precision/recall，不能直接接入生产拒绝。

下一步应先获取可追踪 line/span 和空间校准证据，建立正负样本，而不是提高全页长度阈值。未采集或不可靠的 confidence 必须保持未知。

未来运行诊断可复用 Provider Attempt，消费已有 Native/Raw/normalized 对象，记录 CONFIRMED_LOSS、EVIDENCE_CONFLICT、RISK_UNVERIFIED、UNASSESSABLE 的语义区别。不能因风险就自动升级 Marker、选择 Native、拒绝结果或补全文本。

“有风险时保留 unresolved”作为诊断结论可行；若要把 accepted PAGE 改为终态 unresolved，会改变 Acceptance、escalation 和 Canonical 选择，必须另行批准并验证，不属于第一阶段。

## 7. JudgeAI 历史材料影响

JudgeAI 当前主要消费 Markdown，保存 Canonical/Audit；局部内部 Manifest 风险不会自动通知 JudgeAI。Canonical 或诊断中存在 SupplementalEvidence，也不意味着已进入评审上下文。此轮不能宣称用户能从 HTTP 200/Audit PASS 得知 OCR 的姓名或公式风险。

历史导入的主要风险是权威页错误进入全文上下文，影响作者、机构、技术公式及细节判断。建议对已知复杂扫描论文页保留人工复核记录及导入批次/源摘要关联；不自动重算历史评审或覆盖已有材料。

后续若需机器告知消费者，可独立评估现有 audit warnings 的诊断扩展或其他兼容传输方式；保持 validation.pass 原含义，并确认 JudgeAI 实际读取字段。仅内部新增警告不能当作端到端解决。Markdown 插入说明、Canonical 附属信息或 HTTP 字段扩展都需单独设计批准。

## 8. 最小回归矩阵与新增测试

| 范围 | 第一阶段必须验证 | 后续质量实验 |
|---|---|---|
| case_001、002、004、005 冻结材料 | Canonical/Markdown、选择结果、Native 内容与结构不变，仅诊断新增 | 原生正确内容、表格、标题、页眉/水印和正常公式负样本 |
| case_003 p43/p44 | 4/3 脚注保留、正文不自动插入、原始序号与未知关系不变 | 缺句、姓名首字、上标/电荷冲突；逐区域人工标注 |
| 多 attempt/多 Provider | 每次取证身份唯一，未接受结果可追踪，旧 optional 字段兼容 | 同源冲突不能当多数真值 |
| HTTP/直接 Parser | 相同输入摘要一致、不同输入不同；失败运行记录状态，v1字段不变 | 摘要与 JudgeAI 源身份对照，需未来集成 |
| 生命周期/并发 | 不跨 run 覆盖，不泄漏句柄，不影响 timeout/shutdown/心跳 | 诊断失败不改变路由和任务终态 |
| 存储 | 原子写、配额、失败、过期、路径安全；临时与持久化引用可区分 | 不完整结构给不可评估而不是零风险 |

新增指纹测试：空/大型流式输入、直接与 HTTP、异常路径、输入被修改的显式边界，不保存隐私内容到日志。新增证据测试：连续两页不互相覆盖、同任务不同 Provider/attempt、归档失败、预算超限、合法过期、对象 handoff 无归档回读。

可复用 `test_raw_provider_normalizer_handoff.py`、`test_runtime_normalization.py`、`test_supplemental_evidence.py`、`test_supplemental_diagnostics.py`、`test_fallback_executor.py`、ArtifactPaths、DocumentUnit Renderer/Audit 和 service shutdown 专项。

质量负样本必须包含错误 Native 编码、双栏交错、断词、页码页眉、水印、相同文本不同区域、合法等价公式及扫描页无 Native。公式冲突不得触发补写。初期使用冻结样本与模拟存储验证，再申请少量真实 MinerU 任务验证证据通道；不要求立即重跑完整 case_003。

## 9. 实施优先级与顺序

| 优先级 | 最小行动 | 决策边界 |
|---|---|---|
| P1-1 | 共同入口输入 SHA-256/字节数与早期诊断保存 | 不改变 HTTP/ParseResult/内容 |
| P1-2 | attempt 级原生证据身份、临时/归档状态、有界 allowlist 留存 | 不保存所有大型模型产物；不新增 File Bus |
| P1-3 | 扩大关键区域人工标注与负样本，复核现有历史导入风险 | 不宣称两页普遍准确率，不自动更换材料 |
| P2-1 | 经标注验证后的运行质量风险诊断 | 仅 warning/不可评估，不改变接受 |
| P2-2 | 评估安全附属信息展示与消费者风险传递 | 独立审批 Canonical/Markdown/消费合同 |
| P2-3 | 证据充分后评估质量感知 PAGE 权威选择或 unresolved | 独立审批 Acceptance/路由影响，五例及更大样本回归 |

第一批实现建议仅 P1-1、P1-2。它们解决取证可靠性，**不会自动解决 OCR 错误**；P1-3 是下一批质量决策的必要前提。当前没有依据承诺可靠自动修复姓名、公式或缺句。

## 10. 验证与停止边界

本轮进行源码/冻结产物分析和 `git diff --check`，没有执行 pytest，因此不引用旧通过数量作为本轮结果。只新增本报告；保留现有日志代码、JudgeAI 工具、离线实验及其他未提交修改。没有重启 8010、调用 Provider、改写输出、提交或推送。方案等待确认后实施。
