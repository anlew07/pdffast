# Supplemental Evidence 真实 Worker 验证与安全消费设计

日期：2026-10-09（Asia/Shanghai）。仅两个既有case_003物理页面任务；无整份Pipeline、无路由/接受条件/正文选择修改。

## 1. 结论与环境

当前锁定MinerU 3.4.5真实模型已经完成端到端验证：p43四个、p44三个page_footnote，经内存输出回调 → Worker JSONL → RawProviderResult.supplemental_evidence → Normalizer可选元数据完整传递。最终两页均capture_status=COMPLETE、callback_count=1，执行SUCCESS、当前Acceptance接受；去重没有删块，原index、position、文本、bbox及物理页完整保留。

同时发现并最小修复“回调未被调用时空集合无法与无脚注区分”的诊断缺口。修复前/后各顺序运行同两页一次，总共4次页任务，始终仅mineru_local，不执行其他页或完整case_003。两轮产物均保留，不覆盖前一轮。

- 平台macOS 14.6.1 arm64，8逻辑CPU。
- 实际版本：mineru=3.4.5、torch=2.14.0、torchvision=0.29.0、six=1.17.0、shapely=2.2.0、pyclipper=1.4.0、ftfy=6.3.1；实验驱动对前三版本做明确assert。
- 原runtime配置pipeline/ocr/ch，formula_enable/table_enable=true，原离线模型/env不变。
- 预算：predict每页600秒，preflight60秒、Worker初始化300秒；两个任务串行复用同一个Worker，每轮上限约26分钟另加清理，实际约38秒。
- Worker解释器来自configs/providers.json现有mineru_local；父驱动借用已有只读v2解释器，PYTHONPATH指向v3、禁用bytecode，不修改v2。

## 2. 输入与执行入口

完整阅读supplemental-evidence-contract、mineru-supplemental-blocks-experiment、case003-quality-acceptance-diagnosis，并核对MinerU Worker、实际3.4.5安装函数、JSONL、RawProviderResult、SupplementalEvidence、Normalizer及旧独立实验驱动。

历史根：`outputs/service/api_c20df2b1a1e345439edbf6070a671859`。

| 页 | 原task_id | 原input（相对历史根） |
|---|---|---|
| 43 | s9_0043_page_fallback_5aba61185609 | 09_1_fallback_units/inputs/page/p0043_page.png |
| 44 | s9_0044_page_fallback_4fedefb0cbce | 09_1_fallback_units/inputs/page/p0044_page.png |

使用历史runtime_escalation_policy中原任务及原output_contract，通过Registry.create → preflight → initialize → Provider.execute → normalize_runtime_result → 原_evaluate → close。注册器只创建mineru_local，不走整份Pipeline/升级执行。

原始PNG hash执行前后不变：p43 `b51e100c2695cae7c3d78c3932b026264fb2f5fc6e4f26b7a36a6f06db82d138`；p44 `77a9ef453e01c1f3d832176d6c4b768f3839f1dfee539ec98f672d189013b882`。此前15个冻结实验输入也全部复核不变。

## 3. 固定版本回调与最小修复

真实接口：`mineru.cli.common._process_output(pdf_info, ..., middle_json, model_output=None, process_mode='vlm')`。3.4.5 pipeline的run_output_task传入middle_json['pdf_info']；ThreadPoolExecutor(max_workers=1)执行输出，do_parse等待各future.result()，故捕获完后才发JSONL响应。

原输出函数先正常执行，捕获读取同一内存pdf_info的discarded_blocks，只提取page_footnote。finally恢复函数；主输出异常继续传播，补充提取异常单独诊断，不为脚注破坏Markdown。

**复现的诊断缺陷：** 捕获上下文启用但original callback没有被调用，旧envelope为blocks=[]/diagnostics=[]；这与一次真实回调、合法discarded_blocks=[]相同。两个失败测试先复现缺少状态，然后最小增加：

| capture_status | 含义 |
|---|---|
| COMPLETE | 当前已知结构的捕获回调完成；不是OCR正确性/全文完整性证明 |
| NOT_CALLED | 有效接口已安装，但回调没有发生；CAPTURE_NOT_CALLED诊断 |
| UNAVAILABLE | 无兼容接口/物理页映射/多页映射 |
| FAILED | 补充提取发生异常；SUPPLEMENTAL_CAPTURE_FAILED保留类型/消息 |
| PARTIAL | 已处理，但含未知span类型等不完整证据 |
| EXPORT_FAILED | 原输出异常；主任务继续失败并传播原异常 |
| UNSPECIFIED_LEGACY | 旧无状态envelope的对象兼容表示，不能当成功空结果 |

callback_count记录实际调用次数；validate_supplemental将两字段保留到标准化对象。合法零脚注仅在当前结构符合预期、COMPLETE且调用发生时解释为没有已识别page_footnote。不得将FAILED/NOT_CALLED/UNAVAILABLE的零块解释为无脚注。

版本保护：pyproject精确固定mineru[pipeline]==3.4.5，uv.lock及安装版本已核对；Worker READY提供实际版本，实验明确assert。生产捕获只有签名兼容性检查，**没有硬性的运行时3.4.5拒绝机制**。未来函数名/调用路径变化会触发UNAVAILABLE或NOT_CALLED；如果signature不变而字段重命名/角色含义/单位改变，仍可能语义性漏取。不能凭COMPLETE保证未知未来版本兼容；升级前必须验证pdf_info字段、单位、调用路径及样本结果。没有新文件fallback。

## 4. 两轮真实执行结果

修复前：`outputs/supplemental_evidence_live_validation/run_1cb212cdbd`，p43 execute14.411秒、p44 13.465秒；4/3完整传递，但无捕获状态/计数。轮总37.187秒。

**最终修复后：** `outputs/supplemental_evidence_live_validation/run_a3594c2072`。

| 指标 | p43 | p44 |
|---|---:|---:|
| execute墙钟秒 | 13.918 | 14.103 |
| Worker reported execute秒 | 13.910389 | 14.095932 |
| normalize秒 | 0.001874 | 0.001521 |
| task总秒，含校验/对照 | 13.923 | 14.109 |
| Markdown字符 | 4424 | 4653 |
| SUCCESS / accepted | SUCCESS / true | SUCCESS / true |
| capture_status / callback_count | COMPLETE / 1 | COMPLETE / 1 |

共享preflight5.205秒、available=true/detail=mineru=ok；Worker READY3.719秒；cleanup0.797秒；最终轮总 **37.761秒**。p43首次execute内有模型初始化1.113982秒，已经包含在execute内，不再相加；p44复用Worker/模型。execute包括Provider处理、输出和协议，不称其为纯神经网络推理。

UTC日志02:23:59–02:24:28对应上海10:23:59–10:24:28。保留完整模型stdout/stderr日志和JSON响应，未吞掉异常。两轮均无真实模型异常或超时；故障注入只在测试中执行。

## 5. 逐环节传输与字段验证

| 环节 | p43 | p44 | 证据 |
|---|---:|---:|---|
| Provider原生middle page_footnote | 4 | 3 | 本轮生成的middle JSON，实验结束后核验 |
| 内存捕获 / Worker JSONL | 4 | 3 | worker_response.json，COMPLETE/1 |
| RawProviderResult对象input_count | 4 | 3 | SupplementalEvidence类型，supplemental_object.json |
| 验证去重后output_count | 4 | 3 | 无SAME_REGION_AND_CONTENT合并 |
| Normalizer supplemental blocks | 4 | 3 | normalized_prediction.json，与对象to_dict完全一致 |

后验读取Provider-native sidecar仅在**实验驱动**用于验证，与生产Worker捕获无关，未引入Runtime File Bus。

逐块文本与当前raw lines/spans提取一致，bbox/index/page亦一致；比较zip原始脚注序列，验证所有原始position/order未被重新排序。每块一个来源，来源为task ID + page:0/discarded_blocks/position，全部可追踪；本次没有多表示重复来源输入，不能称本次模型真实触发了来源合并，但已有合成/冻结重复测试覆盖该规则。

p43保留资助、机构/邮件、在线链接、DOI的4块；p44通讯作者、机构和邮件3块。所有authority=SUPPLEMENTAL_ONLY，coordinate_system=mineru_page/unit=pdf_point，坐标属于输入PNG转换后的MinerU PDF页，不自动当成原PDF Native坐标。

被排除：p43 4块（page_number、两个header、footer），p44 9块（page_number、7个header、footer），全部有EXCLUDED_ROLE诊断；未误纳入正文或脚注。p44 footer DOI仍未纳入page_footnote合同。

这里“文本完整”仅指**Provider原生识别内容没有在新对象通道额外丢失**；不能保证原图每字都识别正确。先前正文缺句/姓名/公式问题仍然存在。

## 6. 阅读顺序、重复与正文保护

| 页 | 原脚注index保持 | 局部几何候选 | 状态 |
|---|---|---|---|
| 43 | 14,15,16,17 | 14→15→16→17 | GEOMETRIC_LOCAL_CANDIDATE |
| 44 | 27,28,29 | **28→27→29** | GEOMETRIC_LOCAL_CANDIDATE |

所有body_order=UNRESOLVED。两页脚注实际都在左栏，没有真实跨栏脚注样本；不能冒称跨栏关系已验证可解。正文双栏/脚注跨区域关系未推断，跨栏不确定性由合成测试验证，不生成跨栏连续文本。

两轮均4→4/3→3，没有错误去重，未静默丢来源。缺几何、Markdown文字相同但无空间匹配等仍只能标风险，不能据文字相同删除。

最终两页Worker Markdown与以前冻结document.md**逐字节一致**。对每页同一RawProviderResult移除supplemental对象进行独立Normalizer对照：compact_canonical完全相同，原Acceptance结果相同；新增证据只在独立元数据中。未运行完整新Canonical/Audit，不能将模块合同对照冒称新完整PDF Audit；相应Canonical/Renderer/Audit自动化测试另行通过。

## 7. 回调失败边界与资源

- 原_export异常：仍导致主任务失败，异常不被捕获逻辑吞掉。
- 可选补充提取异常：Markdown导出结果保持，FAILED+错误诊断可见；需要消费方检查状态，而非仅检查有无数组。
- API/页映射不可用：UNAVAILABLE，既有Markdown-only仍可用。
- 回调未调用：新增NOT_CALLED/0+诊断，解决静默成功空结果歧义。
- COMPLETE是当前已知结构提取完成，不是语义覆盖真值；未来字段/单位变化仍需要版本/fixture兼容门禁。
- 局部函数替换只发生在独立Worker，单任务协议串行、finally恢复；不是主服务全局monkeypatch。
- 两轮Worker PID6898/23132在close后标准库检查均已不存在。returncode=null因handle已清除，不伪称已读取0退出码。无后台捕获线程新增。

## 8. 安全消费策略（仅设计B、C；不实现）

### A：接收并保存——当前已实现

保留非权威对象、物理页、原坐标、来源身份、顺序和捕获状态。保存不意味着展示，更不意味着正文替代。

### B：质量诊断——推荐下一步先做

消费capture_status/callback_count/input/output_count/diagnostics，区分无脚注、未执行、提取失败、部分支持、去重及未知映射。记录raw有脚注而正文未表示的**覆盖说明**，不是自动拒绝；缺bbox/关系/顺序标无法评估。

Native/Recovered算法仍有误报漏报，本轮不接入该风险评分。B不需要修改Canonical权威规则或HTTP字段；可以内部诊断/人工证据报告展示，不据此切换Provider。

### C：最终文档附属信息——需要独立批准与验证

page_footnote适合“页面附属信息/原始脚注证据”区域，不默认成为正文或章节。最小建议：在DocumentBuilder内部保留独立supplemental集合，以page/region/source为锚；若需Canonical持久化，再评审一个**独立非权威supplements区域**，不重用正文records，不修改page_fallback authority。

- 作者/机构/邮件关联：仅有对应标记、同页、空间及已确认关系时生成候选relation；同姓名/邮箱不能单独证明关系。无法确认时target=None、relationship=UNRESOLVED，显示“未关联的页面脚注”。
- 文档归属：优先挂物理页；没有已确认DocumentUnit membership时不自动归给Primary或某论文，保留未归属。
- DOI：p43在page_footnote可成为出版信息候选；p44 DOI属footer，当前合同不支持，不根据猜测补造。
- 自动展示前条件：捕获COMPLETE、支持类型、可靠来源/page/bbox、无 unresolved重复风险，并由明确获准的附属展示合同定义；有未知顺序/作者关系时只能独立证据卡或待核验附属说明，不能挤入正文位置。
- 去重：若历史Markdown有同文字但无空间来源证明，不直接删除；有同源身份或可靠相同region与内容证明才可建立“已呈现”关系并避免二次显示，否则保留重复风险供人工处理。
- 位置：每条保留原bbox、坐标单位、page_size和原source；要画在原PDF上必须验证转换矩阵/crop origin，不能直接复用坐标。
- 显示“识别证据，非权威正文”；不把局部几何候选当全局阅读顺序。邮件/资助、参考文献、公式须分别分类，不用同一通用append规则。

HTTP v1：路径、schema_version=1.0、字段集合及ParseResult结构不改。内部诊断无需新HTTP字段。若未来C改变document.md内容或对外document.json增加字段，即使HTTP envelope不变也属于可见内容/schema行为变化，应另行评审版本与严格客户兼容；不能声称加字段天然无风险。可先做独立review产物/内部附属对象，不直接扩充公开Canonical。

### D：权威正文——本轮不设计、不授权

Supplemental Evidence不能自动改写正文、覆盖Native、改变接受或Canonical页面选择。

## 9. 修改、兼容和实际测试

本轮生产最小修复仅：`pdffast/providers/mineru_capture.py`增加捕获状态/计数/未调用诊断，`pdffast/providers/supplemental.py`保留这两字段；扩展 `tests/unit/test_supplemental_evidence.py`两个失败复现/保护测试。其余是本报告与两轮独立实验产物。未改Router、Acceptance、Canonical、Renderer、Audit、HTTP、JudgeAI/v2、依赖版本/配置，未提交或清理。

新测试先失败（缺capture_status），修复后17项合同/IPC测试通过。覆盖合法无脚注与未调用区分、补充异常不影响主结果、原导出异常传播、不兼容API、旧Markdown-only、其他Provider无字段、字段序列化/去重/顺序。

实际结果：

- 最终完整无reference：**407 passed、20 skipped、0 failed，25.65秒**。
- reference-bound相关Provider/Normalizer/Acceptance/Canonical/Renderer：**108 passed、0 failed，2.28秒**。
- reference-bound Audit专项：**18 passed、0 failed，2.84秒**。
- 未重跑reference完整套件；上一阶段423 passed只作为历史结果，不冒称本轮结果。
- git diff --check及15冻结输入hash复核：通过。

无reference完整命令采用现有只读v2解释器并显式指向v3：

```bash
 env -u PDFFAST_REFERENCE_ROOT -u PDFFAST_SAMPLE_PDF \
 PYTHONPATH="$PWD" PYTHONDONTWRITEBYTECODE=1 \
 /Users/admin/Workspace/pdffast-v2/.venv/bin/python -m pytest -q \
 tests/unit tests/contracts tests/regression -p no:cacheprovider
```

reference专项：test_supplemental_evidence、test_provider_lifecycle、test_runtime_normalization、test_raw_provider_normalizer_handoff、test_fallback_executor、test_mineru_dependencies、test_canonical_document_units、test_document_unit_renderer、test_prediction_normalizer_parity；PDFFAST_REFERENCE_ROOT指向 `/Users/admin/Workspace/pdffast`。没有调用其重型模型测试或整PDF003。

## 10. 产物与下一阶段条件

最终根：`outputs/supplemental_evidence_live_validation/run_a3594c2072/`。

- experiment_driver.py、launch.log、experiment.json、worker_ready.json：环境/命令/版本/生命周期与模型运行日志。
- page_43/、page_44/：原task、worker_response.json（真实JSONL）、supplemental_object.json、normalized_prediction.json、verification.json（每环节检查）、document.md、raw/mineru_output/。
- baseline_raw/：移除补充对象的Normalizer对照副产物，非正式outputs。
- process_cleanup.json：回收后的PID检查。
- 修复前根run_1cb212cdbd完整保留，用于说明诊断缺口；不是最终状态验证。

下一阶段可先批准B的capture/accounting诊断消费。C需要附属区域合同、页面/DocumentUnit归属、坐标转换、关系与空间去重验证、对外JSON/Markdown兼容评审。不得将真实通道成功当OCR缺陷已修复；不自动进入C或D。
