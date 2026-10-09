# PDFFast 重构收尾审查与稳定基线规划

日期：2026-10-09。仓库 `/Users/admin/Workspace/pdffast-v3`，分支 `refactor/v3`，HEAD `dcc7af9`。本轮只读审查，只新增本报告。结论限于当前源码、已存产物、测试及明确的历史运行记录，不等同Linux或当前六Provider全量验收。

## 1. 总体结论

**建议冻结当前重构的候选代码基线，完成可复现提交后形成稳定审查点。可以进入隔离的v3 HTTP对照测试；尚不能声明可直接替换正式v2或完成Linux CPU离线交付。** 未发现已证实阻止本机候选冻结的P0。正式集成门槛见P1清单，内容真实性限制须由JudgeAI场景验收，不能用Audit PASS替代。

当前fresh生产主线以对象交接，未发现PDFFast自有中间JSON写出后必须重读才能继续计算的路径。Provider原生输出、配置/模型文件仍合理需要读。兼容file API和旧编号产物保留；公开parse没有resume/reuse能力。

本轮实际无reference完整回归：**420 passed、20 skipped、0 failed，54.09秒**。历史最新reference全套440 passed来自前一诊断任务两轮执行，**本轮未重新运行reference全套**。本轮未模型推理、未HTTP实请求、未Linux运行、未启动或关闭正在工作的服务。

## 2. 源码依据与职责完成情况

| 模块 | 当前源码事实 | 测试/真实验证边界 |
|---|---|---|
| 公开入口/应用层 | `pdffast/parser.py:PDFFastParser.parse`转配置给`application/parse_service.py:ParseService`，加载配置、装配Registry/Normalizer/Context | parse_service、HTTP与日志集成测试；历史真实HTTP仅确认002/003 |
| Native | runner顺序组织Profiler→sections→structure→tables→TextFlow；profile、snapshot_meta/pages、alignment、structure、table均显式传内存 | snapshot_section/structure/table_result及真实reference characterization；不因text_flow文件长判断必须拆分 |
| 结构语义 | `native/sections.py`通用observed heading；`structure_reconciliation`独立候选/裁决/anchor/coverage | 五例结构回归复用Provider结果；PRIMARY.section_ids=()，不将Native section默认归Primary |
| Evidence/Quality/Fallback | runner传Native对象与TextFlowResult给EvidenceReport，随后QualityReport→FallbackPlan→CapabilityPlan | 对象/file等价测试及禁止read测试；Quality与内容真实性不同 |
| 执行计划/执行器 | frozen policy生成ProviderExecutionPlan，executor串行wave/provider/task；Registry负责kind、启用和模型资源校验 | executor升级/终态/lifecycle测试；没有Provider插件发现 |
| Provider/归一化 | RawProviderResult→normalize_runtime_result→normalize_prediction(result_data,known_hashes)→attempt selection | raw-provider handoff测试，不回读自己raw任务JSON或runtime manifest |
| Canonical/Renderer/Audit | runner传selection/alignment/TextFlow/Quality/Capability；Canonical dict→Renderer；Audit直接收运行对象和Markdown | selected_stage10、remaining_object_inputs、canonical/documentunit/audit合同测试 |
| ParseResult | `result.py:from_pipeline`直接取payload canonical/markdown/audit/production_manifest | 无结果文件reload构造；兼容mapping访问保留 |
| ArtifactPaths | `pipeline/artifacts.py`集中18个旧物理字段，result/native/observability/diagnostics/providers派生视图 | semantic_artifact_paths/runner_wiring；executor及底层writer仍拼内部子文件名，未声称所有Path字面量消失 |
| 运行观察 | `runtime.py`ContextVar、独立心跳Event/Thread、finally清理；runtime_format中文Formatter | 成功、异常、并发、资源清理测试；第三方OS stderr不保证按run隔离 |
| Supplemental | MinerU私有回调→JSONL→Raw对象→Normalizer元数据；attempt/manifest诊断，COMPLETE不是OCR正确性 | 43/44真实4/3脚注已验证；本轮新增原始块计数没有重推理，仅测试，正文不消费 |

实际阅读入口、主要对象/file分支、生命周期、配置、接受条件、Canonical页面选择、DocumentUnit及相关测试源码；静态搜索全部核心目录的read/json/open/glob/exists。不是对每个Native算法分支做数学正确性证明。

## 3. 真实运行证据与五种状态

| 能力 | 实现 | 单元/集成测试 | 真实PDF/Provider | 真实HTTP | Linux离线 |
|---|---|---|---|---|---|
| Native/结构/内容对象链 | 是 | 是 | 001～005结构重放；部分002/003/004对象parity | 历史002/003 | 未验证 |
| 六Provider resolve/生命周期 | 是 | lazy factory、fake engine、真实轻量JSONL子进程 | 旧环境单任务报告；最新v3并非六个均重新真实验收 | 历史003实际用了RapidOCR/Paddle文本/Marker，MinerU当时失败 | 未验证 |
| MinerU依赖修复 | 是，3.4.5锁定 | import边界/缺依赖测试 | p34、43、44真实成功 | 修复后整份003未跑 | 未验证 |
| Supplemental对象通道 | 是 | 冻结/模拟IPC/真实来源检查 | p43四/p44三真实回调，COMPLETE/1 | 新诊断尚无新实HTTP | 未验证 |
| 中文日志/心跳 | 是 | 并发与Formatter/计时测试 | 历史长任务心跳真实触发 | 历史002/003，中文展示主要自动化 | 未验证 |

实际读取`outputs/service/*/result/manifest.json`、audit、Markdown和Canonical：

- case002两个run：`api_29a38f98d545410c8ec90bae3f91ead8`、`api_2f4a54044ac04d74bcbf9b23d9031cba`，Audit PASS/true，Markdown14838字符，Canonical1.1。
- case003：`api_c20df2b1a1e345439edbf6070a671859`，66页、Markdown100904字符，Audit PASS/true。production summary实读54task，52 accepted、2 terminal preserve、0 pipeline_failure；Marker10尝试/7selected、MinerU7尝试/0selected、RapidOCR47/44、Paddle文本1/1。
- `case003-performance-diagnosis.md`从原日志记录880.489秒、Provider850.727、Marker740.198、MinerU失败转Marker616.130。HTTP200来自此前用户验证，现有产物不能单独证明状态码，报告明确未留该请求access log。
- `final-structure-regression.md`及`outputs/final_structure_regression/`：001～005审计全部通过，但Provider结果按任务合同核对后复用，不能声称重新执行六模型。
- `supplemental-evidence-live-validation.md`及`outputs/supplemental_evidence_live_validation/run_a3594c2072/`：真实p43/p44约13.92/14.10秒，4/3证据，Worker关闭PID已消失；未构建这次新结果的完整Canonical/Audit。

## 4. 架构审查与遗留边界

```text
HTTP上传→普通PDF路径→Parser→ParseService→runner
→ Native观察/通用章节/页面结构/表格/TextFlow
→ Evidence→Quality→Fallback→Capability→Frozen执行计划
→ Registry/ProviderTask→RawProviderResult→Normalizer→Selection
→ DocumentUnit reconciliation + Canonical→Renderer→Audit→ParseResult→HTTP
```

- fresh分支明确使用`is None`：TextFlow21024附近、Normalizer2733附近、Canonical/document_units对象入口、Audit调用。合法空dict/list不必触发文件fallback。
- `run_stage10`仍有`section_alignment is not None or native.sections.is_file()`：正式runner提供alignment，短路不靠artifact存在；独立file入口才检查文件。Canonical输入hash可由对象计算，selected原始文件仍是provenance引用。
- file分支存在于Native/Evidence/Normalizer/Stage10/Audit CLI，属于兼容或replay，不等于fresh File Bus。Provider读取自产Markdown和模型属于PROVIDER_NATIVE_IO；配置/route candidates属于CONFIG_POLICY。动态import加载`_stage10_builder/_stage10_renderer/_stage10_audit.py`是实现适配，不是中间数据回读。
- `run_core_pipeline`旧docstring称execute_providers=False可使用已有结果，但实际235附近直接raise，不支持该模式。P2文档错误；公开ParseService总是True，不能照旧docstring启动replay。
- absolute `pdffast.*` AST import图未发现环；检查的核心依赖没有反向HTTP依赖。此检查不覆盖相对import及动态字符串所有可能环。合同测试扫描集合未包含application/runtime/structure_reconciliation等新增顶层，应扩展防回归（P2），目前源码未见违禁导入。
- frozen dataclass内部仍可含可变dict，read-only依赖下游约束和特定handoff测试，不是深层immutability保证。现无证据要求重建全部domain类型。
- experiments/case003_quality仅离线，实际按冻结目录读，未进入runtime导入；其测试不在默认tests集合。没有因文件存在就等于正式使用。
- runner持有snapshot、flow、attempt结果至parse结束，大小受PDF/任务数限制，但HTTP无输入并发/页面资源上限，不能说总服务内存有界（P1容量验收）。

## 5. 六Provider可靠性

配置实读`configs/providers.json`并与`pdffast/resources/configs/providers.json`比较，相等。6个runtime_enabled=true；MinerU/Marker benchmark_enabled=false不阻止runtime执行。Registry在create前检查required_artifacts、tree、manifest及指定ONNX SHA256，不因测试绕过生产检查。

| Provider | 环境/preflight/初始化 | timeout/回收 | 当前风险与验证 |
|---|---|---|---|
| RapidOCR | 主环境rapidocr3.9.2/onnxruntime1.30.0；lazy engine，局部文本polygon | 进程内同步执行，无worker级硬timeout；close释放engine引用 | 真实HTTP大量成功；释放Python引用不等于native库内存完全返回OS |
| Paddle文本 | 主环境paddleocr3.6/paddle3.2.1/paddlex3.6.1；import/class probe，本地det/rec | 同上 | 历史003一次成功；未验证最新并发实模型，device=null非明确CPU契约 |
| Paddle VL | 与文本共环境，模型本地目录 | 同上 | class READY与完整推理不同；最新v3实推理/CPU资源需单独验收 |
| Docling | runtimes/docling，2.127，torch2.14，transformers5.17，RapidOCR/ONNX | preflight60/init180/predict300秒，Worker | HF离线及资源tree；历史环境验证不能代替Linux重新构建 |
| MinerU | runtimes/mineru，3.4.5pipeline/torch2.14/torchvision.29/transformers4.57.6/six1.17；probe实际import pipeline | 60/300/600秒，持久Worker | 最新小页真实成功；首次模型载入在execute，READY只表import/Worker就绪 |
| Marker | runtimes/marker，marker-pdf2/torch2.14/transformers5.17；preflight主要package metadata | 60/300/600秒，nonce HOME/进程group/sentinel，converter按运行复用 | 历史单任务最长135.245秒；慢不等于挂死；metadata probe不能证明推理依赖全部可用 |

`workers.py`正常BYE→wait→close pipes；失败/timeout→terminate→wait5→kill→wait5，再按进程身份清理后代。macOS用libproc，其他平台退回ps；ps不可用返回空集，Linux后代发现并无/proc备用，因此容器权限/进程工具必须验证。直接Popen被reap不等于任意第三方后代都有可wait的父关系。

Executor的task异常转FAILED进入原escalation；每task每chain候选一次，没有同task/provider隐式重试。不同task仍可重复遭遇同一确定性执行故障，没有通用Provider熔断；MinerU import问题已前移preflight，preflight失败现在会整段raise，不应宣称自动跳过失效Provider。不得为性能诊断擅自变更策略。

**清理审查缺口（P1）**：executor在initialize成功后才把provider加入providers；初始化之前失败对象不经过该finally.close。JsonLineWorker自身start异常已清理，但任意未来adapter分配后失败不受executor保证。finally顺序close若某adapter close抛异常，可能中止后续close并遮盖原错误；已有测试未覆盖真实HTTP退出时全部此类组合。本轮仅记录控制流风险，未观察到当前泄漏，不判P0。

MinerU捕获依赖3.4.5真实`mineru.cli.common._process_output(pdf_info,...)`，do_parse等待内部output future；适配先原输出再捕获。补充异常诊断不破坏Markdown，原导出异常照常失败。当前signature检查并非完整schema/版本守卫：未来key或类型改名仍可能COMPLETE空结果；版本升级需固定fixture和真实烟测。仅脚注机制不值得大规模Worker重构。

### Ctrl+C：未确定根因

service/app.py没有lifespan/shutdown/active parse取消注册；sync def由框架线程池执行。Worker各自start_new_session，不直接接收终端SIGINT；资源清理依赖解析栈实际退出。用户观察到Uvicorn不能正常退出，本轮未找到可完整复现的server PID/请求状态/信号次数/退出日志，不能判断是线程等待、长推理、Worker泄漏或框架行为。

P1仅要求隔离实验：空闲、原生短解析、轻量Worker等待三种状态，记录第一次SIGINT、请求/线程/worker是否结束及限定grace窗口；再定位取消和finally实际执行，不先改timeout或杀共享模型进程。真实Marker长任务信号实验需另行成本确认。

## 6. 内容质量与合同

- Native accounting、word/page/region provenance与unresolved保留；不是逐字真值。图像、字体编码、双栏顺序、公式天然可能不可靠。
- Normalizer Markdown→text/tables/formulas/reading_blocks，relations常UNSUPPORTED。raw_refs与原文本保留用于取证，但不是所有字段进入最终正文。
- MinerU page_footnote属于discarded结构，不在Provider Markdown；新supplemental通道保留，仅非权威诊断。header/footer/page_number/aside/image默认排除，未知类型带原因；p44 DOI属footer，脚注通道不恢复它。
- `_evaluate`检查执行状态、required text availability、非空文本要求、required structure任一非空；SUCCESS不自动等于接受，但接受也不检查句段/person/formula真实性。p43/44漏句、姓名、化学式错误仍accepted是已证实盲区。
- `_stage10_builder.py:453–506`接受的PAGE OCR/layout成为权威页，单页Native record标SUPPRESS；保留来源记录不保证Native正确句子仍展示。region/inline为保守补充，不能把所有fallback概括为overlay。
- DocumentUnit PRIMARY未自动拥有Native sections，page range PARTIAL/RESOLVED不代表exclusive ownership；Canonical发布经admission的RECOVERED单元，schema1.1，不发布未知parent猜测。Renderer边界marker不是新section标题。
- Audit核对覆盖/结构/provenance/渲染合同；Audit PASS不能保证每个人名、公式正确。Supplemental COMPLETE也同样不是内容真实证明。

对JudgeAI：适合隔离业务对照与人工抽检；若其结论依赖精确姓名/数值/化学式/引用，需明确来源及人工核验策略，暂不能承诺OCR内容可作无复核事实依据。该风险不要求本轮重写Acceptance；验证条件和业务使用范围须获确认。

## 7. HTTP与集成准备

`service/app.py`：multipart `file`，POST /parse，response_model ParseResponse；外层schema_version1.0/run_id/markdown/canonical/audit。内部Canonical实际1.1，不能将外层1.0解释为嵌套schema未变。400用于扩展名/空文件；Core受控错误映射500，其他异常由框架默认500。HTTP200只是parse返回，未由audit.validation.pass强制决定；terminal unresolved可以正常返回。

每请求UUID独立Parser/run_dir，日志ContextVar隔离；TestClient并发测试真实HTTP adapter但mock了计算和Provider，未验证多个大模型同时执行内存/CPU/退出。Worker stderr直接继承宿主FD，保留原始错误但不保证全部第三方行带run_id。

无请求总deadline、无同步断连取消、无并发资源限额；Provider predict timeout不等于HTTP总timeout，RapidOCR/Paddle进程内无相同硬deadline。JudgeAI/反向代理超时需要隔离测试对齐，但本轮不修改其配置。

**可开展隔离替换实验**：保留现v2地址，只用独立端口和输出目录访问v3，先case002合同/错误/audit对照，再确认关闭及并发边界。**不能宣称正式切换已就绪**：shutdown问题未验证、六Provider新环境/修复后003完整路径未验收、Canonical1.1消费及内容质量风险需业务确认。

HTTP上传TemporaryDirectory完成后删除，Canonical provenance可能引用已经删除的原PDF路径；运行时审计对象不受影响，但离线复核需要另保原始输入/哈希和访问策略（P2），现公开parse无resume。

## 8. Linux CPU离线部署差距

实读root及3个runtime pyproject/uv.lock：root Python>=3.12，Worker均>=3.12,<3.13，锁requires==3.12.*；应以Python3.12部署全部，而非只根据Core允许3.14安装。MinerU锁与当前six/torch/torchvision/mineru声明一致；root锁metadata与当前依赖声明吻合。

lock包含Linux wheel记录（各Worker torch/torchvision均2个Linux和1个macOSwheel，root paddle有Linuxwheel），但registry仍PyPI，不等于离线wheel已备齐；没有CPU专用index保证、平台ABI验证或真实CPU-only安装证据。不能以macOS arm64结果外推Linux x86_64/arm64。

部署门槛：

1. 明确Linux发行版/CPU架构、Python3.12、glibc、实际目标wheel及转依赖；断网安装并保存安装清单，不靠自动下载。
2. 4个独立环境（main + Docling/MinerU/Marker）；当前root .venv实测pytest不存在，最新测试借用v2解释器，需在v3独立dev/service环境复现。dev声明仅pytest，HTTP TestClient还需httpx；不能依赖可选模型转依赖偶然提供。
3. Config Marker `${HOME}/Library/Caches/...`、`pdffast-v2/marker-workers`、`${HOME}/.local/bin/llama-server`明显承袭macOS布局；Linux同路径可创建但第三方默认cache/二进制ABI不保证匹配。RapidOCR/Docling路径硬绑定.venv/lib/python3.12，运行目录须符合配置；不是可随意pip-install到任何位置的完整部署合同。
4. 离线模型tree/hash/manifest与MinerU tools JSON实际所指目录一起打包校验；只有存在性检查不证明该JSON路径可用或全部权重真实性。HF_HUB_OFFLINE/TRANSFORMERS_OFFLINE、本地模型目录有保障，不能代替断网推理确认所有第三方下载分支被禁。
5. device=null、CPU推理资源/线程/模型首次加载需验收；llama-server目标平台构建不能复用macOS二进制。
6. ps进程身份发现、select/信号/后代回收在目标Linux验证；运行用户应可读模型、可写output/temp/nonce缓存。未找到Linux安装/健康预检一体入口；/health不验资源。

README和PROVIDER_RUNTIME_ENVIRONMENTS仍主要称v2及旧.venv-*，甚至写“未实现FastAPI”；当前源码已service和runtimes子目录。P1交付前更新准确运行说明，不能照抄旧命令。

## 9. 测试覆盖和20个skip

本轮命令：

```bash
env -u PDFFAST_REFERENCE_ROOT -u PDFFAST_SAMPLE_PDF \
PYTHONPATH="$PWD" PYTHONDONTWRITEBYTECODE=1 \
/Users/admin/Workspace/pdffast-v2/.venv/bin/python -m pytest -q \
tests/unit tests/contracts tests/regression -p no:cacheprovider
```

实际420 passed/20 skipped/0 failed。skip逐组实读pytest结果：snapshot_section2、snapshot_structure3、frozen_config1、source_baseline2、generic_native_sections2、generic_section_continuation2、prediction_normalizer_parity7、profiler_parity1，共20。全部因未设置reference（profiler还需sample）。**不是20个Provider失败被skip。**

历史reference440覆盖这些20项，同时仍有大量mock/冻结/本地文件测试；不覆盖重型模型全运行、并发实模型或Linux。tests/provider不在上述完整命令（只检查preflight pass/skip，不执行模型）；experiments不在默认tests集合。本机local supplemental冻结fixture不存在时还会额外skip，clean clone不能复现当前420/440就绪程度。

重点测试：Provider lifecycle真实JSONL轻量子进程+fake engine、对象handoff禁止read+等价、DocumentUnit synthetic+case003、HTTP adapter真实TestClient+stub计算、中文日志50用例等。大量映射参数化增加计数合理，但通过数字不是独立真实PDF样本数。未建议删除重复检查换数字；未来可将快合同/本地fixture/reference/真实Provider四类门槛明确分开。

不足：当前v3自己测试环境未配dev、HTTP错误/断连/shutdown全栈验收不足、close异常组合、平台特性、空仓库冻结fixture供应、MinerU原计数新增后无新实模型。内容真实性离线实验有误报漏报，未进入Acceptance，不能把11项实验或两页恢复7块当普遍precision/recall。

## 10. 问题分级

| 级别/ID | 事实或风险 | 稳定基线处理 |
|---|---|---|
| P0 | **未发现已证实P0** | 只认可当前本机候选冻结，不外推部署 |
| P1-1 | 服务Ctrl+C关闭未复现；无专用取消/shutdown管理 | 隔离集成前明确grace与资源退出，先复现 |
| P1-2 | 初始化对象纳入finally的时机、close异常中断后续清理 | 故障注入回归确认，再决定最小修复；不是已证明泄漏 |
| P1-3 | 新环境完整case003未跑；MinerU修复可能改变被接受Provider与正文 | 正式切换前获批定向/全案对照人工质量验收，不自动执行 |
| P1-4 | Linux CPU离线无实证，Marker路径/二进制及wheel未适配验收 | Linux交付阻塞；不阻止macOS审查点冻结 |
| P1-5 | 测试借v2解释器、本地fixture/参考外部目录；文档落后 | 独立v3测试环境、fixture供应/哈希清单、准确启动说明 |
| P1-6 | HTTP无总deadline/资源限额；并发模型、嵌套Canonical1.1消费未验收 | 正式JudgeAI集成前业务合同与资源/timeout验收；不要求立即改所有接口 |
| P1-7 | PAGE权威替换 + accepted/audit缺内容真实性保证 | 业务质量限制确认和标注抽检；不是要求本轮重设计Acceptance |
| P2-1 | MinerU私有回调与未来升级schema耦合 | 冻结3.4.5，升级前守卫/实烟测 |
| P2-2 | 当前每Provider每parse复用，但跨task确定性故障无熔断 | 先故障分类实验，不擅改routing |
| P2-3 | 旧编号wrapper/dynamic loader/docstring、契约测试目录漏新层 | 文档/覆盖补齐后续做，不拆大文件 |
| P2-4 | library默认run_id='parse'复用输出，同run_id并发不保证隔离；run_id未验证路径 | HTTPUUID规避，公开library文档/校验单独决策 |
| P2-5 | 原PDF临时路径失效、diagnostics/nonce cache保留增长 | 归档/权限/保留策略单独设计，禁止本轮清理 |

P1表示正式集成/对应平台交付的门槛，可先在受控隔离环境验证；不把所有P1描述成“生产代码已坏”。

## 11. Git收尾方案

只读状态确认27 tracked修改、91 untracked文件（本报告创建前），约716223字节；无tracked/untracked单文件>1MB。git diff --stat仅tracked：1631insert/198delete，不能遗漏untracked新模块和报告。`.gitignore`已忽略outputs/.venv/cache/PDF/log，runtimes锁不被忽略。未发现模型/大型输出已跟踪；未跟踪`:memory:.ses`51字节为本机临时session信息，不建议提交，先保留不删。

HEAD历史已提交Template removal及编号重启、Evidence/TextFlow早期对象化；大量后续R2/R3/R4变更交织于runner/canonical/worker和tests。**不能直接按B1～B15历史顺序逐文件提交**，会把imports指向尚不存在的模块，或让runner/contract不一致。

建议可测试的提交集合（计划，不执行）：

1. **MinerU环境锁定修复**：runtimes/mineru/pyproject.toml + uv.lock，同步包含对应依赖检查所需worker/mineru hunks及test_mineru_dependencies。如与supplemental嵌入存在同文件不可安全隔离，环境声明先提交，代码检查纳入第2项。边界：锁metadata与真实import/preflight/已存小页验收。不把已经存在的未提交大块worker替换掉。
2. **完整一致的Core/结构/对象/产物/生命周期/日志/证据闭合快照**：所有相互依赖的pdffast修改、新structure_reconciliation、canonical/audit DocumentUnit、runtime_format、supplemental/capture及对应tests，root pyproject变更一并。边界：独立checkout完整420/20和reference440、HTTP合同、冻结输入hash。这是较大的原子提交，但优于人为制造不可测试阶段。若要拆成“生命周期”“结构与对象”“观测与supplemental”，须先在隔离临时树逐hunk构造并实际跑各依赖门槛；本轮不创建/改树，不保证现状可直接三拆。
3. **审查/验收文档**：docs/reviews，明确各历史版本/命令/真实与replay区别；README旧名称修订须另获编码授权。报告中绝对本机路径可作为历史证据但不能充当部署命令。
4. **离线实验**：experiments/case003_quality可单独提交；其本机outputs依赖需清楚README/manifest要求。原始PDF/用户文档/模型/outputs不加入Git；冻结小fixture是否可进入仓库需内容授权，不能擅自复制。否则外部受控fixture归档和hash清单。

每一步用显式文件清单审查，不用git add .；本轮禁止且未执行add/commit/push/reset/clean。合并第1、2为一个完全可测试候选也可行；不要为了提交颗粒度改解析行为。最终tag只在确认提交内容和独立环境测试后另获授权创建。

## 12. 冻结决定与最小下一步

**可冻结：Native通用结构、R3对象驱动、R4语义路径、当前HTTP envelope与Supplemental仅诊断边界，作为本机验证的候选代码快照。**

**未冻结为交付承诺：Linux CPU离线可运行、六Provider最新完整可用、修复后case003质量/性能、Ctrl+C及时退出、OCR内容真实性。**

最小行动依次：

1. 用户确认候选冻结范围及原子提交方案；在独立v3环境复现测试，明确外部fixture供应。
2. 隔离端口做HTTP v1/Canonical1.1兼容、轻量关闭/取消/错误和并发资源边界验收，保留现JudgeAI地址。
3. 针对关闭/cleanup风险只在复现后做最小修复；不扩展Provider插件或Stage架构。
4. 经确认预算再运行修复后case003对照，重点原MinerU失败页面及业务事实质量，而非只看200/Audit。
5. 明确Linux目标平台再准备离线wheel/model/config/llama-server验收清单和断网小页烟测；本轮不下载或写Docker。

完成审查后停止，等待确认。
