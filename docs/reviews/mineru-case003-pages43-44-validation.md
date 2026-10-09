# case_003 MinerU 第 43、44 页定向验证

## 1. 结论

只运行了两个原始 PAGE_FALLBACK 任务，按页 43 → 44 顺序执行，仅使用 mineru_local。两页均 SUCCESS，Normalizer 成功，当前生产接受条件均返回 accepted=true、rejection_reasons=[]。没有运行完整 case_003，没有修改任何生产逻辑、配置、原始输入、路由或质量门槛。

**执行成功与接受成功，不等于内容质量等价。** 原图与历史 Marker 对照发现第 43 页正文缺句、第 44 页化学式损坏，两页部分脚注/出版信息未进入 normalized text。当前接受条件不会检测这些问题。不能据此建议直接改变路由，也不能宣称质量不变的加速。

## 2. 环境、输入与执行入口

- 平台：macOS 14.6.1 arm64，8 个逻辑 CPU；本次没有采样 CPU/GPU 利用率。
- 版本：torch 2.14.0、torchvision 0.29.0、mineru 3.4.5；six 1.17.0、shapely 2.2.0、pyclipper 1.4.0、ftfy 6.3.1。
- 先读取 `case003-performance-diagnosis.md` 和 `mineru-runtime-dependency-fix.md`，再确认原任务、输入、配置与接口。
- 真实入口：当前 ProviderRegistry 创建 mineru_local → preflight → initialize → execute → normalize_runtime_result → Executor 既有 `_evaluate` → close。实验驱动仅保存于实验目录，不进入生产模块。
- 当前原配置：backend=pipeline、parse_method=ocr、lang=ch、formula_enable=true、table_enable=true；保留原离线配置和本机模型目录。
- 单任务预算 600 秒；preflight 60 秒、Worker 初始化 300 秒。两个任务复用一个 Worker，顺序执行；理论预算合计 1560 秒（26 分钟），另加少量整理/清理时间。

历史运行根目录：`outputs/service/api_c20df2b1a1e345439edbf6070a671859`。

| 页 | 任务 ID | 原输入（相对历史运行根目录） | 图像尺寸 |
|---|---|---|---|
| 43 | s9_0043_page_fallback_5aba61185609 | 09_1_fallback_units/inputs/page/p0043_page.png | 1650×2200 |
| 44 | s9_0044_page_fallback_4fedefb0cbce | 09_1_fallback_units/inputs/page/p0044_page.png | 1654×2205 |

两任务 required capability 均为 PAGE_DOCUMENT_LAYOUT_PARSE。原 MinerU 分别约 0.060 / 0.056 秒失败，原因均为 `ModuleNotFoundError: No module named 'torchvision'`，随后升级至 Marker；历史 Marker 两页均 SUCCESS、accepted=true。

输入执行前后 SHA256 一致：

- p43：`b51e100c2695cae7c3d78c3932b026264fb2f5fc6e4f26b7a36a6f06db82d138`
- p44：`77a9ef453e01c1f3d832176d6c4b768f3839f1dfee539ec98f672d189013b882`

## 3. 真实执行与耗时

共享 preflight：available=true、detail=mineru=ok，耗时 **5.349 秒**；共享 Worker 初始化至 READY **3.056 秒**。第 43 页为该 Worker 首任务，第 44 页复用同一 Worker。

| 指标 | 第 43 页 | 第 44 页 |
|---|---:|---:|
| 历史 Marker 任务窗口（秒） | 122.065 | 118.217 |
| 历史 Marker Worker 报告耗时（秒） | 122.055149 | 118.207996 |
| 当前 MinerU execute 墙钟（秒） | 14.275060 | 14.296905 |
| 当前 MinerU Worker 报告执行耗时（秒） | 14.268485 | 14.290786 |
| Normalizer（秒） | 0.001424 | 0.001195 |
| 接受判断（秒） | 0.000028 | 0.000010 |
| 任务总耗时，含归一化/判断/任务记录（秒） | 14.276954 | 14.298572 |
| Markdown 字符数 | 4424 | 4653 |
| normalized text 字符数 | 4414 | 4518 |
| 执行状态 | SUCCESS | SUCCESS |
| 当前条件接受 | true | true |
| rejection_reasons | [] | [] |

Worker READY **不是模型已完成加载**：第 43 页 execute 内日志记录 DocAnalysis 模型初始化 1.272588 秒，已包含在该页 execute 中；不能重复加算，也不能把 execute 全部叫作纯模型推理。第 44 页无第二次该初始化日志。执行时间还包含模型处理、Provider 输出和读取，不具备精确拆分纯神经网络推理的仪表。

若把共享准备成本只分配给第一任务，第 43 页约 22.682 秒，第 44 页边际约 14.299 秒；末尾共享 cleanup 0.831 秒。两任务完整实验 **37.819 秒**，包含共享准备、执行、记录和 cleanup。

历史两个 Marker 窗口合计 240.282 秒；当前两个 MinerU execute 合计 28.572 秒，观测差约 211.710 秒；若与当前完整冷启动实验比较，差约 202.463 秒。历史 Marker 已在较早任务初始化，本次第一 MinerU 任务包含冷加载，运行时间与系统负载也不同。这是历史对照，不是受控基准；质量等价尚未成立，不能称为已经验证的无损收益，更不能外推全部 54 项任务。

## 4. Normalizer 与现有接受条件

| 结构通道 | MinerU p43 | MinerU p44 | 历史 Marker p43 | 历史 Marker p44 |
|---|---|---|---|---|
| reading_blocks | AVAILABLE，10 | AVAILABLE，16 | AVAILABLE，14 | AVAILABLE，36 |
| tables | UNSUPPORTED，0 | UNSUPPORTED，0 | NOT_EMITTED，0 | NOT_EMITTED，0 |
| formulas | AVAILABLE，2 | AVAILABLE，3 | AVAILABLE，3 | AVAILABLE，4 |
| relations | UNSUPPORTED，0 | UNSUPPORTED，0 | UNSUPPORTED，0 | UNSUPPORTED，0 |
| normalized text 字符数 | 4414 | 4518 | 5279 | 4852 |

现有 `_evaluate` 要求成功状态、AVAILABLE 的非空文本，以及 reading_blocks 或 tables 至少一个 AVAILABLE 非空列表。两页满足这些条件，故被接受；没有计算逐字准确率、语义完整性、数学式正确性、脚注完整性或列关系。块数/公式数也不能直接当作质量指标。

## 5. 内容与结构对照

对照依据是原任务 PNG（两页均实际查看）、本次 MinerU Markdown/normalized prediction、历史归档 Marker canonical prediction。Marker 原生临时输出可能被后续运行复用，故不以可变目录代替归档证据。历史归档文本实际存在，已复制为 `historical_marker_text.md`。Marker 也不是人工真值。

### 第 43 页

- 原页是 GaAs 开关英文论文首页，含标题、作者、摘要、Index Terms、双栏 Introduction、底部资助/机构/邮件/DOI。不是数据表页。
- MinerU 保留原标题并生成 heading，Introduction 独立为 heading；正文主要双栏延续顺序合理，未观察到整栏消失。
- 明确漏字/漏句：作者 Chengang Dong 被识别成 **hengang Dong**。Introduction 原文开头为 “THE development of new terahertz (THz) generation sources is of important scientific and technical interest for a large variety of applications.”；MinerU 为 **“HE development of new terahertz (THz) generation a large variety of applications.”**，既丢首字母，又丢重要句段。原图与 Marker 均保留该句段。
- 原文数量级 10^8 被输出成 `1 \dot{0}^{8}`，带多余点；部分空格合并，例如 Asthe。
- manuscript/funding、机构、邮件、DOI 未进入 MinerU normalized Markdown，但仍在 raw middle JSON 的 discarded_blocks 中；已抽取 `discarded_text.txt`。保留 raw 不代表正式 normalized 内容没有遗漏。
- Marker 保留上述底部元数据，但把它们插在左右栏正文之间，阅读顺序同样存在取舍；部分在线 URL 也缺失。因此不能把 Marker 全文作为绝对正确答案。

### 第 44 页

- 原页为 anthracene 分子 DFT 论文首页，含作者/五个机构、ARTICLE INFO、ABSTRACT、双栏 Introduction、出版与通讯信息。
- MinerU 正确分开标题、ARTICLE INFO、ABSTRACT、Introduction；正文双栏续接大体合理，未观察到整栏消失。
- 作者 Qungui Wang 后机构标记 b 丢失，College of Science 对应机构标记 c 丢失；作者—机构关系未显式恢复。
- 原文 nano-TiO₂ 被输出成 **`nano- $\mathbf{\cdot} \Gamma \mathbf{i} 0_{2}$`**；原文 I₃⁻ 的负电荷在 `(4) I3 ...` 中丢失。Marker 对这两处保留得更好。公式通道 AVAILABLE 不等于公式正确。
- 通讯作者、邮件、DOI 及部分期刊页眉未进入 normalized text，但 raw discarded_blocks 中存在；期刊图像以 image 引用保存，独立 review Markdown 的图片也已复制。
- Marker 的 36 个 reading_blocks 部分来自把日期/关键词切成小块，不能据此判定其结构一定优于 MinerU 的 16 块。

### 两页共同边界

- 两页没有可供验证的数据表；ARTICLE INFO 是元数据布局。表格行列/单元格恢复不能通过这两例验证，结论为 **未覆盖**。
- 双方 relations 均 UNSUPPORTED，列关联、作者—机构等关系无法从该通道确认。
- 对非空 reading_blocks 做整块文本规范空白后的重复检查，未发现完全相同重复块；未做穷尽的局部重复检测。
- 未生成逐字人工真值或 WER/CER；上述是可核实的视觉抽查和具体差异，不是完整全文准确率评价。

## 6. 资源与异常

两页均未超时，没有缺依赖异常、OOM 或失败返回。Worker PID 66271 在 close 后以标准库检查已不存在。`worker_returncode_after_close=null` 是 Worker 清除了 process handle，不能据此声称有已记录的零退出码。

Darwin `RUSAGE_CHILDREN.ru_maxrss` 为 2525888512 字节，约 2.35 GiB；这不是整棵进程树的同时峰值，也不代表完成了内存压力监测。CPU 利用率未采样。完整 Worker 响应、stdout/stderr 日志均保留，没有为了通过实验改变接受条件。

## 7. 后续建议与路由结论

- 环境修复有效：这两个过去立即报缺依赖的任务现在真实完成且通过既有接受条件。
- **维持现有路由与门槛，本轮不建议据此直接调整。** 修复环境后，MinerU 被当前条件接受会自然阻止后续 Marker；本次发现的正文/公式损失必须先人工核验，不能假设更快等于相同质量。
- 值得进一步验证，但先检查本报告的具体内容问题，再由用户批准扩大样本；优先覆盖真正带表格的任务以及其他原失败输入。
- 原 7 个 MinerU 失败页中，本轮之外有 5 页：34、35、49、51、59；34 已在依赖修复验收成功，所以尚未新增验证的为 **4 页：35、49、51、59**。本轮未自动运行它们。
- 不需要现在重新跑完整 case_003；两例不能预测整份 PDF 的内容质量或 54 任务总收益。

## 8. 自动化测试

实际执行 MinerU dependencies、Provider lifecycle、runtime normalization、RawProviderResult handoff、fallback executor/acceptance、ProviderRegistry、reference prediction-normalizer parity 测试：**80 passed，0 failed，2.19 秒**。

使用只读的现有 v2 环境解释器，以 `PYTHONPATH` 指向 v3；设置 `PYTHONDONTWRITEBYTECODE=1`、关闭 pytest cache，并传入 PDFFAST_REFERENCE_ROOT。没有修改 v2。命令：

```bash
PYTHONPATH="$PWD" PDFFAST_REFERENCE_ROOT=/Users/admin/Workspace/pdffast \
PYTHONDONTWRITEBYTECODE=1 /Users/admin/Workspace/pdffast-v2/.venv/bin/python -m pytest -q \
 tests/unit/test_mineru_dependencies.py tests/unit/test_provider_lifecycle.py \
 tests/unit/test_runtime_normalization.py tests/unit/test_raw_provider_normalizer_handoff.py \
 tests/unit/test_fallback_executor.py tests/unit/test_provider_registry_runtime.py \
 tests/regression/test_prediction_normalizer_parity.py -p no:cacheprovider
```

本轮没有运行完整回归、HTTP 服务或完整 case_003，不把先前冻结基线作为本次实测结果。`git diff --check` 另行检查。本轮只新增报告与实验产物，不提交、清理、重置既有工作区。

## 9. 人工检查入口

实验根目录：`outputs/mineru_case003_pages43_44_validation/run_3fe3efd98b/`。

- `experiment.json`：环境、原配置、共享准备/清理、每任务统计。
- `experiment_driver.py`、`launch.log`：可核验执行入口及完整运行日志。
- `page_43/`、`page_44/`：task.json、verification.json、worker_response.json、normalized_prediction.json。
- 每页 `document.md` 对照 `historical_marker_text.md` 和原输入 PNG；`discarded_text.txt` 可查看未进入 normalized 文本的元数据。
- `raw/mineru_output/`：原生 Markdown、content lists、middle JSON、图片；`provider_raw/`：PDFFast raw sidecar。

完成后停止，未扩大任务范围。
