# case_003 解析性能诊断与 Provider 执行策略评估

## 1. 总体结论

本轮只审计现有源码和产物，未执行 Provider、未重跑 PDF、未修改生产代码/配置/路由、未提交或清理工作区。唯一仓库新增文件为本报告。

主分析运行：`outputs/service/api_c20df2b1a1e345439edbf6070a671859`。result/manifest.json 确认 case_003.pdf；page_profile/render_manifest 确认 66 页；document.md 实测 100904 字符；audit.validation.pass=true，errors=[]，warnings=[]。日志 parse_finished=880.489 秒，与用户数据吻合。HTTP 200 来自用户已验证结果，当前产物没有该请求的 Uvicorn access log，不另行伪称重测 HTTP。

- Provider 执行窗口 **850.727 秒，占总墙钟 96.62%**。
- Marker 10 次 task 窗口 **740.198 秒，占总墙钟 84.07%**，是主要成本。
- 54 个任务共 65 次 Provider 尝试；52 个被接受，2 个 terminal unresolved，0 个 pipeline_failure。HTTP/Audit 通过不等于全部增强任务恢复成功。
- 7 次 MinerU 缺 torchvision 失败合计仅 3.711 秒，但导致 7 个 layout PAGE 任务转交 Marker，这组 Marker 成本为 **616.130 秒**。
- 没有发现低成本结果已经 accepted=true 后还对同一任务执行 Marker，也没有同一 task/provider 重复重试。
- 依赖修复后第 34 页现有单页验证输出可以通过原 acceptance 条件，预计这页可在 MinerU 停止升级；其余 6 页是否同样满足结构质量仍待验证。616.130 秒是可能被替换的旧成本，不是可以承诺的净节省。

## 2. 数据来源与计算方法

读取 pipeline.log 中 200 个 JSON 事件，按 `(provider, task_id)` 配对全部 65 个 task_started/task_finished，配对无缺失。每次 task 窗口覆盖 execute、normalization、结果评估及相应 I/O，不等于纯推理时间。Provider 初始化窗口从 initialization_started 到 initialized，含 Registry/preflight/READY，并不保证内部模型已加载。

读取 production_execution_manifest.json、54 个 selected_predictions、provider_raw、provider_plan.json、runtime_escalation_policy.json、profile/result/audit/render manifest，以及之前单页 MinerU 验收的 verification/normalized_prediction。

Executor 源码为同步串行 wave/group/task 循环；观测 task 时间窗没有交叠，因此本次可以相加为串行贡献。Provider 内部服务器可有线程/并行 slots，其内部耗时不能作为额外墙钟重复相加。使用 monotonic elapsed_seconds 的差值，显示精度为毫秒；下表所有不重叠区间合计恰为 880.489 秒。

未找到独立 Pipeline Report 或细分 Normalizer timer；result/manifest 是产物索引，不是性能报告。

## 3. 分阶段墙钟

| 范围 | 起止 elapsed（秒） | 墙钟（秒） | 范围说明 |
|---|---|---:|---|
| 准备 | 0–0.005 | 0.005 | 首个 Native 事件前 |
| 原生观察/Profiler | 0.005–8.975 | 8.970 | 含 profile/snapshot 写出 |
| 章节发现 | 8.975–8.997 | 0.022 | 含其旁路 artifact |
| 页面结构 | 8.997–9.199 | 0.202 | 同上 |
| 表格恢复 | 9.199–9.295 | 0.096 | 同上 |
| TextFlow | 9.295–14.728 | 5.433 | 原生分析总窗口 14.723，不能再重复相加 |
| Evidence | 14.728–19.234 | 4.506 | 含 artifact |
| Quality | 19.234–21.930 | 2.696 | 含 artifact |
| Fallback Planning | 21.930–27.906 | 5.976 | 含统一输入图渲染，不只是计划计算 |
| Capability Routing | 27.906–27.909 | 0.003 | 含 artifact |
| Frozen execution policy 准备 | 27.909–27.917 | 0.008 | 含 policy 写出 |
| Provider 执行全窗口 | 27.917–878.644 | 850.727 | 详见下表 |
| Canonical handoff | 878.644–878.649 | 0.005 | 边界间开销 |
| Canonical | 878.649–880.062 | 1.413 | 含 reconciliation 和产物 |
| Renderer 边界 | 880.062–880.063 | 0.001 | 间隙 |
| Renderer | 880.063–880.081 | 0.018 | 含 Markdown/manifest |
| Audit | 880.081–880.104 | 0.023 | 含产物 |
| 公共结果写出/退出 | 880.104–880.489 | 0.385 | 含上下文/日志结束，不全部认定磁盘 I/O |
| **合计** | | **880.489** | 不重叠 |

Provider 全窗口细分：初始化/preflight 合计 53.511；65 次 task 窗口合计 791.256；剩余 5.960 秒是未细分的任务间隙、cleanup、selection manifest/prediction 写出等，**不能直接命名为 Normalizer**。

Marker canonical 中 worker elapsed 合计 740.1034，task 窗口比其多 0.0946 秒；RapidOCR raw elapsed 合计 44.1404，task 窗口多约 2.8516 秒。差值仅能作为 execute 外围+Normalizer+I/O 等组合近似；没有独立计时，不能精确拆分 Normalizer 或 selection。Paddle canonical elapsed 缺失，MinerU 失败没有推理 elapsed。

## 4. Provider 耗时与接受统计

以下“成功”指 canonical status SUCCESS/SUCCESS_WITH_WARNINGS；“接受”由 Executor._evaluate 判定。

| Provider | 尝试/独立任务 | 成功 | 失败 | 接受 | 拒绝 | task 墙钟合计 | 最小/中位/P90/最大（秒） | 初始化窗口 |
|---|---:|---:|---:|---:|---:|---:|---|---:|
| Marker | 10/10 | 10 | 0 | 7 | 3 | 740.198 | 1.321 / 86.637 / 122.065 / 135.245 | 0.262 |
| MinerU | 7/7 | 0 | 7 | 0 | 7 | 3.711 | 0.053 / 0.060 / 3.355 / 3.355 | 34.318 |
| RapidOCR | 47/47 | 47 | 0 | 44 | 3 | 46.992 | 0.194 / 0.829 / 2.150 / 2.589 | 0.191 |
| PaddleOCR 文本 | 1/1 | 1 | 0 | 1 | 0 | 0.355 | 单次 0.355 | 18.740 |
| **合计** | **65** | **58** | **7** | **52** | **13** | **791.256** | | **53.511** |

P90 使用 nearest-rank，样本量小，仅描述本次，不代表生产 SLA。拒绝包括明确失败；SUCCESS 但 rejected 共 6 次，全部原因是 `EMPTY_TEXT_WHEN_REQUIRED`：Marker 3 次（inline p42、region p25、region p32），RapidOCR 3 次（region p25、region p32、region p57）。本次没有 SUCCESS 因结构通道缺失被拒绝；MinerU 的结构缺失是异常后的伴随条件，不能误判成其模型结构能力不够。

Marker：7 PAGE + 2 REGION + 1 INLINE；MinerU：7 PAGE layout；RapidOCR：24 PAGE OCR + 22 REGION + 1 INLINE；Paddle：1 REGION。

### 初始化、冷启动与复用

每个 Provider 只出现一次 initialization_started/initialized。Executor providers dict 跨 wave 复用对象；RapidOCR/Paddle `_engine` 缓存；MinerU/Marker Worker 持久化。Marker ensure_converter 按配置 signature 复用 converter/models。保留的后续 9 个 Marker raw worker_response 均为 converter_created_now=false、converter_init_seconds=0，说明这些任务不是反复创建 converter。

但 Marker READY 前只建立协议；真正 create_model_dict/ensure_converter 在第一次 execute。故 0.262 秒是 Worker+preflight 边界，不是全部模型冷启动。第一个 inline Marker raw 后来被 RapidOCR 的同 task raw 覆盖，无法直接取到其 converter_init_seconds。MinerU 旧 preflight 34.318 秒也包含导入成本，不能当成模型推理时间。

## 5. 最慢任务列表

| Provider | task_id | 页/类型 | task 秒 | 接受 | 拒绝原因 |
|---|---|---|---:|---|---|
| marker_local | `s9_0049_page_fallback_9c2b39d10fa8` | 49 / PAGE_FALLBACK | 135.245 | 是 | — |
| marker_local | `s9_0043_page_fallback_5aba61185609` | 43 / PAGE_FALLBACK | 122.065 | 是 | — |
| marker_local | `s9_0042_inline_context_fallback_7ae8402f600c` | 42 / INLINE_CONTEXT_FALLBACK | 120.268 | 否 | EMPTY_TEXT_WHEN_REQUIRED |
| marker_local | `s9_0044_page_fallback_4fedefb0cbce` | 44 / PAGE_FALLBACK | 118.217 | 是 | — |
| marker_local | `s9_0051_page_fallback_68670adee3aa` | 51 / PAGE_FALLBACK | 114.856 | 是 | — |
| marker_local | `s9_0059_page_fallback_72b055c260ca` | 59 / PAGE_FALLBACK | 58.418 | 是 | — |
| marker_local | `s9_0034_page_fallback_32afc416c678` | 34 / PAGE_FALLBACK | 35.118 | 是 | — |
| marker_local | `s9_0035_page_fallback_74073a75896d` | 35 / PAGE_FALLBACK | 32.211 | 是 | — |
| mineru_local | `s9_0034_page_fallback_32afc416c678` | 34 / PAGE_FALLBACK | 3.355 | 否 | PROVIDER_EXECUTION_ERROR, TEXT_CHANNEL_UNAVAILABLE, EMPTY_TEXT_WHEN_REQUIRED, REQUIRED_STRUCTURE_CHANNEL_UNAVAILABLE |
| rapidocr_ch_light | `s9_0062_page_fallback_08283a17000a` | 62 / PAGE_FALLBACK | 2.589 | 是 | — |

### 四个指定任务

| task_id | 输入类型/图像尺寸 | 真实路径与耗时 |
|---|---|---|
| s9_0042_inline_context_fallback_7ae8402f600c | INLINE；2009×71 窄横条 | Marker SUCCESS 120.268 秒，空文本拒绝 → RapidOCR SUCCESS 0.809 秒，接受。输出是页眉/上下文 OCR；不能仅凭接受认定公式质量等价 |
| s9_0034_page_fallback_32afc416c678 | PAGE layout；1654×2339 | MinerU 3.355 秒缺 torchvision → Marker 35.118 秒，接受 |
| s9_0043_page_fallback_5aba61185609 | PAGE layout；1650×2200 | MinerU 0.060 秒同环境错误 → Marker 122.065 秒，接受 |
| s9_0044_page_fallback_4fedefb0cbce | PAGE layout；1654×2205 | MinerU 0.056 秒同环境错误 → Marker 118.217 秒，接受 |

### 为什么有约 120 秒的 Marker 任务

另外找到一份本机 Marker llama-server 日志：
`/Users/admin/Library/Caches/pdffast-v2/marker-workers/388cf0dd35f246e9bd114848b14a5e55/.cache/datalab/surya/llamacpp_server.log`。

路径含 v2 是当前 v3 配置的缓存 namespace，读取不代表执行 v2。它是运行时间窗内唯一新建的同类日志：文件出生时间 2026-10-08 16:13:58.503（上海）；10 个请求的完成顺序及时间与本次 10 次 Marker task 相符。主 parse 从 16:12:09.348 到 16:26:49.836。此关联有很强时间证据，但没有显式 run_id/worker_id join，仍将其标为相关服务日志，而不是凭文件名绝对认定。

| 对应 Marker 任务 | llama prompt（秒） | decode（秒） | 服务端请求合计（秒） | 输出 token |
|---|---:|---:|---:|---:|
| 首个 inline p42 | 1.105 | 1.385 | 2.490 | 83 |
| p43 | 10.884 | 106.787 | 117.671 | 5944 |
| p44 | 11.038 | 102.890 | 113.928 | 5797 |
| p49 | 10.793 | 119.519 | 130.313 | 6473 |
| p51 | 10.655 | 100.058 | 110.714 | 5539 |

后四页的 decode 约 54–56 token/s，说明长输出生成是主要贡献，不是简单等待固定 120 秒或超时。task 仍成功且接受；当前 predict_timeout=600，日志没有这些任务 timeout。

首个 inline task 从 16:12:37.527 到 16:14:37.795；其 server 日志开始建立于 16:13:58.503，约晚 80.976 秒；server 在自身相对 35.165 秒才报告 model loaded/listening，随后首请求仅 2.490 秒。约 117.778 秒不在该请求 prompt+decode 内，包含 converter/后台服务冷启动及其他前后处理，不能全部叫纯推理。没有保留首任务 converter_init_seconds，不能进一步精确拆分。

10 个服务请求 prompt+decode 合计 595.769 秒（prompt 78.241、decode 517.528），是 Marker 740.198 秒 task 窗口的内部子集，不能再加到总运行时间。其余差值含冷启动、图像/布局/转换处理、协议等，尚无细分 timer。

Marker 配置 use_llm=false 并不意味着不使用本地生成模型：Marker/Surya 底层仍运行本地 GGUF OCR 服务；该开关禁止的是额外 LLM service 路径。

## 6. 升级与潜在重复处理

本次 batch_history：wave0 Marker 1、MinerU 7、RapidOCR 46；wave1 Marker 9、Paddle 1、RapidOCR 1。Provider 分组按名称 sorted，不是全局价格排序；组内串行 execute，同一 task 最多走到当前 chain 下一项。

- 11 个 escalated task：7 个 PAGE（MinerU→Marker）、1 INLINE（Marker→RapidOCR）、2 REGION（RapidOCR→Marker→terminal）、1 REGION（RapidOCR→Paddle）。每个本次都恰好两次尝试。
- accepted=true 后状态 done，后续 wave 跳过。已接受低成本结果后还执行重型 Provider的例子为 **0**。
- 65 个 `(task_id, provider)` 组合不重复；不是同模型失败后重试，而是同输入换 Provider 升级。7 次同样环境错误属跨任务重复失败，旧代码没有故障熔断；依赖提前检查已在前一轮修复。
- 54 个 PNG 的 SHA256 全部不同，没有字节相同输入可直接消除；同页 region/page 可能覆盖重叠内容，但语义/范围/合同不同，不能自动当成重复任务删掉。
- 第 43/44/49/51 页 Marker 虽慢，但提供有效阅读块/公式等结构并通过 layout 合同；RapidOCR 平面 OCR 不能据速度直接替代。
- INLINE Marker-first 来自 frozen policy 的数学上下文需求，源码明确不以 DEV 特例拆分。p42 的当前结果提示可实验，不证明所有 inline 都可改 RapidOCR-first。
- 7 个 layout PAGE 原 chain 为 MinerU→Marker→Docling，本次 Marker 全部接受，Docling 未执行。修复 MinerU 后：p34 新 normalized result 通过现有 `_evaluate`（True, []），5 reading_blocks/3 tables，具备在第一项停下的证据；p35/p43/p44/p49/p51/p59 尚无修复后的同任务结果。

### 串行等待与可并行空间

首个 Marker inline 阻塞了同 wave 的 MinerU/RapidOCR 组约 120 秒；第二 wave Marker 组完成前 Paddle 与最后一个 RapidOCR 任务均等待。仅重排串行任务会改善局部进展顺序，不会消除必须执行的时间，也不会让同步 HTTP 提前返回。

并发可能重叠部分初始化/轻 OCR 与 Marker，但有内存、CPU 线程超额竞争、GPU/Metal 竞争、Provider thread safety 和输出覆盖风险。IsolatedWorkerProvider 默认 raw_output_dir 是 input.parent；PAGE 任务共享目录，Marker result.md/metadata.json 与 MinerU mineru_output 会复用/覆盖路径；当前串行 Normalizer立即消费可运行，未来不能直接并行同一 Worker或同目录任务。runtime_manifest.json 也为共享写入点。必须先隔离实验输出和资源，再考虑调度，不能只套线程池。

## 7. 当前 CPU 环境与结论边界

当前主机 Darwin/arm64，8 个逻辑 CPU（只反映现在，不是历史利用率采样）。相关 llama-server 日志记录 n_threads=4、n_slots=8、n_ctx_slot=12288，**8 slots 不等于 8 个 PDFFast 任务并发**；本次客户端逐任务同步。

没有历史 CPU utilization、RSS、swap、GPU/Metal/offload 统计。当前 Surya TORCH_DEVICE 自动 CUDA→MPS→CPU，LLAMA_CPP_NGL 默认99；日志没有实际 Metal/GPU offload 结论。因此不能把本次880秒严格归为“纯CPU算力不足”，也不能承诺加线程就变快。已证实的是串行结构和模型生成输出长度成本；图像分辨率/预处理/上下文长度/内存压力属于待测原因。

SURYA_INFERENCE_KEEP_ALIVE=False 在实际 installed spawn.py 中控制进程退出时的 atexit cleanup，不意味着每个任务重启。后续 converter_created_now=false 和单 server 日志覆盖10请求证实本次已有复用，不能把改 keep_alive=true 当成逐页加速修复；跨请求常驻还会改变资源/隔离生命周期。

## 8. 优化机会与风险排序

| 优先级/风险 | 机会 | 证据与收益边界 | 质量/资源影响 | 验证方式 | 公共合同 |
|---|---|---|---|---|---|
| P0/低 | 验证已修复 MinerU 的7个 layout PAGE | 原 Marker PAGE 成本616.130秒；p34已真实成功并满足原合同。净收益=被替代 Marker/故障成本减新增 MinerU及冷启动差，其他6页成本未知，不承诺倍数 | 对比文本、阅读顺序、表格、公式、provenance；接受条件通过不是完整质量等价 | 先 p43/p44 同输入单页，原阈值不变 | 不需 |
| P1/低 | 补齐实验分段计时、冷/热分类 | Marker首inline冷开销很大，后页热执行依然长；需要在实验驱动记录 converter/server/load/decode/normalize，收益为定位，不直接加速 | 仅实验观测，保证不改 parser 内容 | 隔离实验计时与服务log关联 | 不需 |
| P2/低 | 以输入hash+provider/version/config/模型/normalizer版本做重复请求缓存可行性评估 | 本次54图无同字节重复；对单次case003的直接cache收益目前为0证据，跨请求命中率待测 | 防止陈旧结果/provenance错误、磁盘/RAM保留；当前公开parse无resume合同 | 仅离线重复同输入实验，先确认一致性 | 内部可不需；公开reuse需另议 |
| P3/中 | 批处理/有界异Provider调度 | serial导致轻OCR/初始化等待；可重叠成本有限且互相争资源，收益待测，不将provider内部slots视为并发能力证明 | 峰值内存/oversubscription、路径覆盖、线程安全、确定性 | 先独立输出目录，2任务上限，对比wall/峰值RSS/结果字典 | 不需改HTTP字段，但需内部安全设计 |
| P4/中 | 跨parse热Worker池 | 本次同run已复用，无再造converter证据；只能针对下一次请求冷启动，收益上限不能按所有任务倍乘 | 常驻模型RAM、并发串扰、异常恢复、cleanup变更 | 同图同worker两次与两次fresh对照；不改现有共享池 | 理论不需；运维生命周期需评审 |
| P5/高 | INLINE快速通道/Provider顺序调整 | p42 Marker120.268秒空文本、Rapid0.809秒接受；仅一个样本，不能外推数学公式质量 | 可能漏公式/上下文或损失native证据 | 先同p42逐Provider结果/人工核验，再多inline样本characterization | HTTP可不变，但运行/质量行为改变需确认 |
| P6/高 | force_ocr/分辨率/生成长度/接受策略调整 | 大页decode生成5500–6500token；可研究但尚无安全参数证据 | 截断/漏正文表格、结构排序退化；更快不等于相同质量 | 逐页对照，禁止以仅Audit PASS作为质量等价 | HTTP可不变，但内容行为改变需确认 |

“缓存/初始化复用”类别不意味着本轮发现可以无风险马上实现：已有同run复用不应重复建设；跨run缓存/池需版本和资源边界验证。修改接受策略优先级最低，不能为了减少拒绝接受空文本。

## 9. 下一轮具体实验方案（等待确认，本轮未执行）

### E1：优先验证修复后的 layout 路径

- task IDs：`s9_0043_page_fallback_5aba61185609`、`s9_0044_page_fallback_4fedefb0cbce`。
- 输入从本次 provider_plan.json 提取原 PNG；现 MinerU 固定配置、原合同、离线模型；一个fresh Worker依次处理两页，独立实验目录，finally close。
- 记录preflight/READY/每页execute/normalize/原evaluate、raw refs、峰值RSS可用数据，并与原Marker accepted内容人工对比；不改正式Router。
- 预计成本：p34现有fresh全程17.56秒不能外推dense文档。本次批准前预算 **最多每页600秒predict + preflight60秒 + init300秒，约26分钟上限再加cleanup/Normalizer**；常见耗时待测，不承诺实际几秒。两个任务，不是66页。
- 判断：两页既快又满足结构合同和人工质量证据，再决定其他4页是否测。

### E2：Marker冷/热单输入对照

- task ID：`s9_0042_inline_context_fallback_7ae8402f600c`，同2009×71输入、现有Marker配置。
- 一个fresh Worker先后两次execute同图，不改正式任务算法；保存两个独立输出、converter_created/init_seconds及server请求timing。复用结果是否仍空也需记录。
- 预计成本：历史首次120.268秒；热执行本输入没有可靠数据，不能估为零。实验按两个600秒predict + 60秒preflight + 300秒init预算，约26分钟上限再加cleanup，通常成本待测。
- 判断：分离模型冷启动与converter对窄横条的实际行为，决定是否值得更广泛inline方案；不据一个样本修改route。

### E3：低并发调度可行性（E1/E2之后再确认）

- 候选：`s9_0034_page_fallback_32afc416c678` 的 MinerU 与 `s9_0062_page_fallback_08283a17000a` 的 RapidOCR，互不共享Worker与raw目录。
- 串行/2路并发对照，稳定结果、原接受条件及峰值内存采样；没有实现安全隔离前不执行。
- 成本需先采两者热态串行baseline，不给加速倍数；批准时设沿用600秒重型task timeout的资源预算。调度变更若拟进入正式代码，另行评审。

## 10. 数据缺失与限制

- 未获得该请求HTTP access log、独立Pipeline性能Report、Normalizer/selection独立timer、首Marker converter_init_seconds。
- 上游raw task JSON按task_id覆盖；p42后来RapidOCR覆盖此前Marker raw，不能靠现在raw文件恢复首Marker详细参数。部分Provider-native文件路径也被后任务复用，因此只使用可信已归档canonical/事件与明确匹配raw字段。
- Marker server日志的关联基于唯一时间窗与10个顺序完成时间；没有显式run_id，token生成细分结论应带此关联边界。
- 当前源码/依赖已修复，历史运行记录代表修复前行为；current config不等于历史环境完整snapshot，不能虚构历史设备利用率。
- 两个terminal unresolved仍符合保留原始证据策略；Audit PASS只验证其合同，不证明OCR完全正确。
- 本轮没有执行性能实验、没有运行pytest（未改代码），未复用先前410/390数字冒称本轮测试。仅静态读取、文件hash/图像头、原evaluate纯计算与git diff --check。

到此停止；任何额外推理须确认具体实验与预算后进行。
