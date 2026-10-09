# Supplemental Evidence 对象合同、去重与阅读顺序验证

日期：2026-10-09。范围仅限内部非权威证据合同及传递；未改变正文、路由、Acceptance 或 Canonical页面权威选择。

## 1. 现有合同与兼容性点

完整阅读质量归因、supplemental离线实验、Native/recovered风险实验三份报告，并检查 RawProviderResult、Worker JSONL、MinerU 3.4.5实际安装源码、runtime Normalizer、reading_blocks、compact_canonical及接受逻辑。

原 RawProviderResult 为 provider/task_id/status/payload/markdown/elapsed_seconds/warnings；Worker 响应返回 markdown_path/raw_refs，父进程读取Provider原生Markdown。MinerU normalize_mineru只从text提取正文reading_blocks，不能从其raw_refs取得已识别脚注。

`do_parse` 不返回结构，也没有公开结果回调。固定3.4.5版本的 `mineru.cli.common._process_output` 接收内存pdf_info；其pipeline输出线程由do_parse内部等待future完成。采用**独立Worker内的临时捕获适配器**：调用原输出函数不变，再提取内存里的page_footnote，以现有JSONL响应传回。finally恢复原函数；不新增线程，不读取middle/content_list旁路文件，不改MinerU安装文件。

这是有版本耦合的内部适配：检查签名是否含pdf_info。不兼容/未知物理页/多页映射无法确认时输出诊断，不猜页码，不回读文件。原导出失败继续传播，补充捕获失败单独记录SUPPLEMENTAL_CAPTURE_FAILED，不伪称脚注完整。固定版本仍需未来真实小页烟测验证，不冒称本轮重新推理过。

## 2. 数据路径

```text
MinerU 内存 pdf_info
 → 原 _process_output（行为保持）+ 临时补充捕获
 → JSONL response.supplemental_evidence（version=1）
 → IsolatedWorkerProvider.execute
 → validate_supplemental
 → RawProviderResult.supplemental_evidence: SupplementalEvidence | None
 → runtime_normalization
 → normalized prediction 可选 supplemental_evidence 元数据
```

该字段不进入text/tables/formulas/reading_blocks/relations，不成为Acceptance条件。已有Provider无字段时仍为None，normalized prediction不新增该键。显式空envelope与缺字段不同，不触发文件fallback。

runtime raw sidecar持久化经过验证的supplemental对象，既有file Normalizer可重放同一元数据；fresh runtime仍使用result_data内存对象。原Provider Markdown读属于既有PROVIDER_NATIVE_IO，不新增PDFFast自有JSON数据总线。

## 3. 最小对象与字段

新增 `SupplementalEvidence`，沿用项目现有frozen dataclass + Mapping模式；to_dict/from_dict提供JSON序列化，公共读取blocks/diagnostics/local_order_groups返回副本。扩展RawProviderResult一个默认None字段，不建立平行Provider结果类型。

| 字段 | 含义 |
|---|---|
| version | 内部证据合同1；非HTTP schema_version |
| input_count / output_count / diagnostics | 接收、保留数量及排除/合并原因 |
| block_id / source_ids / source_locators | 证据ID、task来源、原始position/index；合并时保留来源别名 |
| evidence_type / original_type / authority | PAGE_FOOTNOTE / page_footnote / SUPPLEMENTAL_ONLY |
| text | 识别文字，不纠正事实或公式；仍可能包含模型错误 |
| page | 输入任务物理页43/44，不用印刷页码或模型page_idx代替 |
| bbox / original_bbox / page_size | 经验证及原始几何、坐标空间尺寸；无可信几何保留文字并标未知 |
| coordinate_system / unit | mineru_page / pdf_point，指MinerU输入转换后的PDF页面点单位，不等同原PDF Native bbox或PNG像素 |
| local_order / body_order | 局部几何候选状态 / 正文相对顺序UNRESOLVED |
| uncertainties | 失效bbox、未知空间、相同来源冲突、Markdown匹配、跨栏不确定性等 |
| local_order_groups | 单页脚注区域的候选序列，独立于原始blocks顺序 |

只支持单PAGE_FALLBACK任务的可靠物理页映射。region/inline缺此映射不强行接收；多页文档产生MULTIPAGE_MAPPING_UNAVAILABLE。未来若扩展必须增加crop-origin/page-transform合同。

page_footnote示例：物理p44、原index28、bbox=[39,681,295,700]、单星通讯作者与机构；text不变，provider_id=mineru_local，source_ids含task及discarded_blocks定位；authority=SUPPLEMENTAL_ONLY、body_order=UNRESOLVED。

## 4. 分类及安全降级

- 仅明确page_footnote成为Supplemental Evidence，正文reading_blocks保持原样。
- header/footer/page_number/aside_text/image排除并记录EXCLUDED_ROLE；未知块记录UNKNOWN_TYPE，不能伪装脚注。
- 未知span记录UNKNOWN_SPAN_TYPE；已知文字/公式span仅提取原content，不自动修公式。
- 空文本、物理页不匹配记录原因；无有效bbox不丢文字，以INVALID_BBOX/DEDUP_GEOMETRY_UNAVAILABLE标记。
- 坐标维数/有限数/范围检查；未知坐标系/单位不能授权空间去重或排序。
- 本轮仍未处理footer DOI、作者关系、参考文献分类、独立公式语义；不是对所有discarded的通用正文恢复器。

## 5. 去重规则

仅在**Provider、物理页、原始类型、坐标空间/单位、page_size、精确bbox和规范空白后的完整文本均相同**时合并。理由SAME_REGION_AND_CONTENT，记录被合并source及index/position，input/output数量可追踪。middle/content_list多表示若已明确对齐到相同坐标对象，则可用同一规则；不引入运行期扫描三份文件。

不删除：

- 同页不同区域相同文本。
- bbox缺失、不可靠或略有不同的文本。
- 相同source_id却几何/内容不一致；保留并标SOURCE_ID_CONFLICT_OR_UNVERIFIABLE。
- Markdown出现同文本但没有空间对应；标MARKDOWN_TEXT_MATCH_WITHOUT_SPATIAL_PROOF，继续保留。
- 同区域不同内容；保留并标SAME_REGION_CONTENT_CONFLICT。

仅规范空白，不删除标点或公式字符，不使用宽松字符集合相等作事实去重。真实重复块若坐标略有偏移会保留；这是保守的重复风险，不为“数量漂亮”删内容。当前未实现模糊空间去重/完整Markdown空间关联。

真实p43/p44为4→4、3→3。两倍重复表示测试为8→4、6→3，并保留来源；合成不同区域同文本2→2，缺几何重复2→2。

## 6. 阅读顺序

原始blocks输入顺序与source_index/position保留；另给local_order_groups，不排序或改写Markdown正文。

同一页按左/右/跨栏范围分组。可信局部顺序仅当相邻块top和bottom均严格递增；轻微bbox重叠不自动判死，但不宣称语义阅读顺序已证实。无法几何确定或跨中线区块标UNRESOLVED；跨组/跨栏标CROSS_COLUMN_ORDER_UNKNOWN。所有正文相对顺序仍为UNRESOLVED。

冻结结果：

| 页 | 保留数量 | 原index顺序 | 局部几何候选 | 正文相对顺序 |
|---|---:|---|---|---|
| 43 | 4 | 14,15,16,17 | 14→15→16→17 | UNRESOLVED |
| 44 | 3 | 27,28,29 | **28→27→29** | UNRESOLVED |

p44修正的是“候选序列表示”，不是将正文/脚注强行串起来。离线旧原型对任何重叠全标未知；本轮允许两条垂直边界都递增时给GEOMETRIC_LOCAL_CANDIDATE，仍未提升为权威顺序。不能据列中线自动推断完整阅读顺序。

## 7. Canonical / Markdown / Acceptance / HTTP边界

_normalize_mineru正文计算没有改；新增的是normalize_one可选证据元数据重放。compact_canonical明确只取既有权威字段，忽略supplemental_evidence；对应测试比较有/无证据时整个compact结果相等。text/reading_blocks/formulas/tables/relations不变，现有Renderer不插入此字段。

Executor._evaluate保持原代码。有/无补充证据接受结果一致。Canonical权威页选择、Router/Policy、HTTP v1、ParseResult、Audit、ArtifactPaths均未修改。

raw与normalized Provider诊断产物会多出可选元数据，相关raw hash可能相应改变；不声称所有raw/normalized文件字节完全相同。正式文档内容选择和Markdown规则不变。Native覆盖风险检测仍只在experiments中，不进入Runtime。

## 8. 本轮修改文件

生产文件：

- `pdffast/providers/supplemental.py`：最小对象、校验、来源合并与局部顺序。
- `pdffast/providers/mineru_capture.py`：stdlib-only内存捕获代码，嵌入隔离Worker。
- `pdffast/providers/mineru.py`：注入捕获、现有响应添加字段、任务物理页传参。
- `pdffast/providers/workers.py`：可选响应验证并放入RawProviderResult。
- `pdffast/providers/base.py`：可选对象字段。
- `pdffast/providers/runtime_normalization.py`：显式对象持久化及内存handoff。
- `pdffast/providers/normalization.py`：file/object路径保留可选证据元数据，正文算法不变。

测试 `tests/unit/test_supplemental_evidence.py`；本报告；独立验收产物 `outputs/supplemental_evidence_contract/page_43.json`、page_44.json、frozen_inputs_verification.json。

工作区本来已有大量重构diff；上述为本轮扩展位置，不能把整个git diff统计归成本轮修改。未重置、覆盖其他工作，未改v2/JudgeAI、未提交Git。

## 9. 验证

- 测试先在对象模块缺失时失败，再实现；新增15项覆盖真实4/3脚注、页/bbox、多来源重复、异区域不误删、未知/装饰类型、局部/跨栏顺序、显式空envelope、无证据其他Provider、JSON往返、file replay、权威内容/接受结果不变。
- 真实JSONL子进程测试使用实际JsonLineWorker+完整MinerU WORKER_CODE，仅模拟模型模块，两个顺序task验证隔离传递与Markdown不变；不是实际MinerU模型推理。
- 捕获恢复及原输出异常继续传播；不兼容签名有诊断。
- 真实冻结结构通过相同捕获代码，不重推理；15个冻结输入SHA256全部保持。
- 不启动完整case_003，不重新执行重型Provider。

实际完整测试结果在下方补充；仅借用只读的v2解释器，PYTHONPATH指向v3、禁用bytecode与pytest cache，不写v2。使用verification-before-completion流程确认真实输出，不引用旧基线代替本轮结果。

## 10. 下一阶段前置条件

1. 对新捕获适配做一个获准的小页真实模型烟测，确认固定3.4.5真实线程回调与响应行为；本轮未推理。
2. 若未来接入正文，需独立评审脚注/出版信息角色、正文相对位置、空间去重和原文完整性，不能凭SUPPLEMENTAL存在改变权威内容。
3. 扩大多栏/跨页/裁剪/缺bbox/不同角色标注样本，解决未知顺序，保留人工核验。
4. MinerU升级时验证私有接口；不兼容仅告警，不新增sidecar回读。
5. Acceptance风险实验单独扩样/校准，本轮不授权拒绝策略或Provider切换。

到此停止，不进入正文插入或Acceptance改造。

### 实际测试结果和命令

| 验证 | 实际结果 |
|---|---|
| 最终无reference完整unit/contracts/regression | **405 passed，20 skipped，0 failed，26.00秒** |
| reference-bound完整unit/contracts/regression | **423 passed，0 skipped，0 failed，133.71秒** |
| 最终reference相关专项（含全部15项新增测试） | **49 passed，0 failed，1.21秒** |
| 新增对象合同/IPC/冻结数据测试单独运行 | **15 passed，0 failed，0.23秒** |
| git diff --check | 通过 |
| 冻结15输入hash复核 | 全部不变 |

计数说明：reference完整运行包含当时13项新增测试；其结束后补了2项“不兼容回调/原导出异常”和“微小几何差异/显式空envelope”测试，这2项以及原13项已在最终49项reference专项中全部通过。没有将两次结果相加宣称一次425 passed；最终无reference完整405已包含全部15项。

```bash
# 无reference完整回归
 env -u PDFFAST_REFERENCE_ROOT -u PDFFAST_SAMPLE_PDF \
 PYTHONPATH="$PWD" PYTHONDONTWRITEBYTECODE=1 \
 /Users/admin/Workspace/pdffast-v2/.venv/bin/python -m pytest -q \
 tests/unit tests/contracts tests/regression -p no:cacheprovider

# reference完整回归
 PYTHONPATH="$PWD" PYTHONDONTWRITEBYTECODE=1 \
 PDFFAST_REFERENCE_ROOT=/Users/admin/Workspace/pdffast \
 PDFFAST_SAMPLE_PDF=/Users/admin/Workspace/pdffast/benchmark/samples/real/case_002.pdf \
 /Users/admin/Workspace/pdffast-v2/.venv/bin/python -m pytest -q \
 tests/unit tests/contracts tests/regression -p no:cacheprovider

# 最终reference专项
 PYTHONPATH="$PWD" PYTHONDONTWRITEBYTECODE=1 \
 PDFFAST_REFERENCE_ROOT=/Users/admin/Workspace/pdffast \
 /Users/admin/Workspace/pdffast-v2/.venv/bin/python -m pytest -q \
 tests/unit/test_supplemental_evidence.py \
 tests/unit/test_raw_provider_normalizer_handoff.py \
 tests/unit/test_runtime_normalization.py tests/unit/test_fallback_executor.py \
 tests/regression/test_prediction_normalizer_parity.py -p no:cacheprovider
```

测试中两次临时失败分别为测试使用了Marker错误的结果路径键、构造JsonLineWorker漏传必需的dependency_probe_code；按真实现有合同纠正测试后通过，没有更改生产Provider合同来迁就测试。
