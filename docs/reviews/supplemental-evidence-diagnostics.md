# Supplemental Evidence 诊断接入与可观测性

日期：2026-10-09。范围仅为诊断，不修改正文、Acceptance、Router、Audit pass 语义或 HTTP v1。

## 现有架构与接入位置

已阅读对象合同、真实Worker验证、脚注实验和质量归因报告，检查真实执行器、Normalizer、ArtifactPaths、Runtime及中文Formatter。每个任务的 selected prediction wrapper 原已包含所有 attempts（包括拒绝候选），production execution manifest 已是运行观察产物。复用这两个结构：attempt 增加 `supplemental_diagnostics`，production manifest 增加同名摘要列表和各候选 accepted 状态；不增加独立报告总线、路径或线程。

正式数据路径：Worker 内存捕获 → JSONL → RawProviderResult.supplemental_evidence → Normalizer，执行器从同一次运行 RawProviderResult 生成诊断。既有对象及Normalizer内容传递不变。诊断文件写出后不重新读取以决定解析。

存放位置沿用 ArtifactPaths.providers：

- `<run_dir>/09_8_production_fallback/selected_predictions/<task_id>.json` 的 `attempts[*].supplemental_diagnostics`。
- 同目录 `production_execution_manifest.json` 的 `supplemental_diagnostics[*]` 是运行摘要投影，带 accepted，便于检查未被选择的候选；它不是新的事实来源。
- 既有 `diagnostics/logs/pipeline.log` 保持结构化日志，控制台通过原Formatter显示中文；日志捕获关闭时不承诺生成pipeline.log。

一个实际执行尝试一份摘要，不新增重试或同一事件的JSON/中文双重控制台输出。attempt与manifest均保留是详情和汇总投影，消费者不应相加统计。未开始的Provider无attempt；整段执行异常尚未写最终manifest时，沿用现有日志保留规则，不承诺新的断点恢复。

## 数据合同

| 字段 | 语义 |
|---|---|
| run_id / provider_id / task_id / page_number | 当前 observation 与 RawProviderResult / task 中的关联信息；独立无observation入口 run_id=null |
| capture_status / callback_count | 已有捕获状态与实际回调次数；无有效数据时不填零 |
| raw_block_count | 回调实际看到的 discarded_blocks 数量，不包括正文 para_blocks；旧输入未记录时null |
| input_count | 送入补充证据校验的块数，非整页全部内容块 |
| eligible_count | 通过类型、页码、非空文本校验的数量，含空间去重前重复表示 |
| deduplicated_count / reason_counts | SAME_REGION_AND_CONTENT 合并次数以及排除/未知类型/捕获异常等原因分布 |
| retained_count | 完整捕获时最终保留数量；未执行、失败、部分捕获、不可用时null |
| observed_retained_count | 实际已观察到的部分保留数量；有envelope时可为0，但不代表完整捕获总数 |
| spatial_complete | 所有保留块具有可信bbox、page_size、已知单位和坐标系；无块时null |
| local_order_statuses / body_order / uncertainty_counts | 局部几何候选和正文相对未知分开，不声称语义全序 |
| diagnostics / attempt_error | 原因、来源定位、捕获原始错误；执行/归一化异常另保留attempt_error |

摘要不复制脚注全文，不改上游共享对象。不完整的 input/eligible/dedup/retained 总计均为null；partial已观测块数量另记。旧协议缺原始总量不能由跳过原因推算成确定数量。

## 捕获状态语义

沿用 COMPLETE、NOT_CALLED、FAILED、PARTIAL、UNAVAILABLE、EXPORT_FAILED、UNSPECIFIED_LEGACY。仅为缺协议的诊断增加 MISSING（当前MinerU应支持但没有字段）和 NOT_SUPPORTED（其他现有Provider无通道），没有创建新的运行枚举。

- COMPLETE + retained_count=0：合同捕获执行完成，没有符合条件的脚注。
- COMPLETE + retained_count>0：捕获完成，有证据；不是OCR准确/全文完整证明。
- NOT_CALLED：回调未执行，不能解释为无脚注。
- FAILED / PARTIAL：异常或未支持span导致不完整；保留原因和已观察数量。
- UNAVAILABLE：接口/页映射/协议不兼容。非法回调次数或未知状态也标诊断不可用，不改变主解析。
- MISSING / NOT_SUPPORTED / UNSPECIFIED_LEGACY：分别表示缺失、当前未支持、旧合同无状态；数量未知。

Worker整条JSONL响应损坏仍遵守原Worker错误传播，本轮不将其改造成成功；supplemental字段缺失/格式错误只诊断，不把补充捕获失败升级为PDF失败。原Markdown导出异常仍按既有合同传播。

## 去重、空间及顺序

不修改原去重规则：同Provider、物理页、类型、坐标空间、page_size、精确bbox、完整规范空白文本一致才合并，原因SAME_REGION_AND_CONTENT；文本相同但区域不同不删，Markdown文字匹配但无空间证明不删。诊断只统计既有结果。

保留来源定位与reason列表；局部GEOMETRIC_LOCAL_CANDIDATE不是权威阅读顺序，正文关系仍UNRESOLVED。缺bbox/跨栏/几何冲突按原不确定性统计。没有风险分数转成拒绝或Provider切换。

## 真实冻结样例与中文展示

本轮未重新推理。对上一轮真实执行 `run_a3594c2072` 的对象可生成以下摘要：

| 页 | 状态 | callback | input/eligible/dedup/retained | raw_block_count | 顺序 |
|---|---|---:|---|---|---|
| 43 | COMPLETE | 1 | 4/4/0/4 | null（当时未记录） | 局部几何候选，正文UNRESOLVED |
| 44 | COMPLETE | 1 | 3/3/0/3 | null（当时未记录） | 原index27,28,29；局部28→27→29；正文UNRESOLVED |

不会为旧真实产物补造 raw_block_count。新回调代码在已取得的内存discarded集合上记录len，专项测试验证2个装饰块、0脚注时raw=2/input=0；没有增加文件读取。

示例（Formatter测试及冻结对象摘要，非本轮新HTTP运行日志）：

```text
[PDFFast][补充证据] 捕获诊断 | 运行编号：run_xxx | Provider：MinerU（provider_id=mineru_local） | 任务编号：s9_xxx | 捕获状态：捕获流程完成 | 页码：43 | 保留证据：4 | 顺序：局部几何候选，正文关系未知
```

仅有已观察证据、或MinerU非COMPLETE状态时发一条事件 `supplemental_evidence_observed`。完整且空不刷屏，其他Provider无支持不刷屏，但每个attempt仍保留诊断。英文事件和字段不变，原JSON日志能力保留。

## 兼容与资源

新字段均为内部诊断的可选扩展。既有Canonical/text/reading_blocks、渲染、Acceptance、HTTPv1/ParseResult、ArtifactPaths均无修改。生产manifest schema_version不变；严格禁止未知JSON键的外部消费者需接受这一向后兼容扩展。

使用原 observation/contextvar，run_id独立；摘要为新dict，不共享可变累积器。diagnostic调用原_emit，不更新last_progress，不新增心跳、线程或后台队列。日志sink沿用原异常隔离。未使用诊断文件exists决定fresh runtime控制流。

## 修改文件

- pdffast/providers/mineru_capture.py：记录实际discarded原始块数。
- pdffast/providers/supplemental.py：保留该可选计数，提供纯诊断摘要。
- pdffast/fallback/executor.py：每个attempt及production manifest添加诊断，选择性发原日志事件；_evaluate/链/升级不变。
- pdffast/runtime.py：只发诊断、不修改真实进展的接口。
- pdffast/runtime_format.py：集中中文映射与简短状态/数量/顺序显示。
- tests/unit/test_supplemental_diagnostics.py：新增诊断、并发、manifest拒绝候选、计时不变、原始计数和异常协议测试。
- 本报告。

其他已有未提交重构保持原状；未提交、清理或修改v2/JudgeAI。

## 验证

专项测试先失败（摘要API不存在/中文事件未识别），实现后验证状态、缺协议、格式异常、去重、空间、正文顺序、并发、混合Provider以及拒绝候选持久化。原有对象合同测试覆盖真实4/3脚注、JSONL回调异常、Markdown-only、Canonical和Acceptance不变；完整套件包含HTTPv1合同及心跳生命周期。

实际结果见下方。本轮解释器只读借用现有v2虚拟环境，PYTHONPATH指向v3，禁用bytecode和pytest cache；不写v2。

## 剩余风险与下一阶段条件

固定MinerU内部接口仍有版本耦合，COMPLETE不是识别真实性证明；升级需真实小页烟测和schema固定测试。未知角色/脚注正文关系/原始PDF坐标变换未解决。其他Provider是否将来支持不能由名称永久推断；新增支持须更新缺协议诊断判定。

仅诊断允许进入生产。自动正文消费前需角色及作者关联证据、空间去重、局部和跨栏顺序人工核验、Canonical隔离附属信息合同及HTTP兼容评审。Native覆盖风险仍离线；不因状态直接拒绝或插入正文。

### 本轮实际执行结果

- 最终诊断专项（诊断13项 + 既有Supplemental/Executor/中文日志合同）：**87 passed，0 failed，0.30秒**。
- 最终无reference完整unit/contracts/regression：**420 passed，20 skipped，0 failed，25.73秒**。
- reference-bound完整unit/contracts/regression：**440 passed，0 failed，159.48秒**。
- git diff --check：通过。
- 冻结15输入SHA256：全部不变。
- 冻结真实对象摘要实际重放：p43 COMPLETE/1/4→4，p44 COMPLETE/1/3→3，均未伪造原始总量，正文顺序UNRESOLVED。

完整回归命令：

```bash
env -u PDFFAST_REFERENCE_ROOT -u PDFFAST_SAMPLE_PDF \
PYTHONPATH="$PWD" PYTHONDONTWRITEBYTECODE=1 \
/Users/admin/Workspace/pdffast-v2/.venv/bin/python -m pytest -q \
tests/unit tests/contracts tests/regression -p no:cacheprovider

PYTHONPATH="$PWD" PYTHONDONTWRITEBYTECODE=1 \
PDFFAST_REFERENCE_ROOT=/Users/admin/Workspace/pdffast \
PDFFAST_SAMPLE_PDF=/Users/admin/Workspace/pdffast/benchmark/samples/real/case_002.pdf \
/Users/admin/Workspace/pdffast-v2/.venv/bin/python -m pytest -q \
tests/unit tests/contracts tests/regression -p no:cacheprovider
```

测试阶段曾出现构造FakeProvider配置漏填kind的测试错误，按真实Registry合同补齐测试配置，没有放宽Registry校验。初次无reference419通过后增加非法捕获元数据测试，最终420包含所有13项新增诊断测试；不将两轮通过数相加。

重复reference-bound全套复核亦完成：**440 passed、0 failed，276.54秒**。两轮均使用同一命令；不将通过数相加，耗时不作为性能基准。
