# R3-B9 Evidence Object Input Convergence

日期：2026-09-30。范围只包括 Evidence 对四个 Native artifact 的输入传输；Evidence accounting、schema、writer、Quality 和后续阶段均未改动。

## 原读取点与消费字段

`create_evidence_report` 原先依次调用 `load_json(profile_path)`、`load_snapshot(snapshot_path)`、`load_json(alignment_path)`、`load_json(structure_path)`。这是正式 Evidence 的四个文件读取点；没有另一套正式 loader。Stage5 已在 R3-B1 优先使用 `table_result`，Stage6 的 noise、reading order、paragraphs 和 normalized flow 已从 `TextFlowResult` 取得，均不需要重新读取文件。

`build_manifest` 从 snapshot meta 取得 `source_file`、页数、版本并校验连续页；从 snapshot 页取得原生 words、区域/图像/表格候选及 provenance；从 profile 页取得页面分类和统计；从 alignment 页取得 section/zone 归属；从 Stage4 页与 validation 取得 blocks、region、bbox 和结构诊断。Stage5 表格项及逻辑表、Stage6 flow/noise/paragraph 数据参与 word、region、table、final-flow 记账。各对象还提供上游版本、source refs、文档/页面引用。传入的路径字符串仍用于 Evidence `inputs` provenance，不再作为正式计算输入。

## 新对象链与兼容接口

```text
Profiler profile + snapshot_meta/pages
  → Section Discovery alignment
  → Page Structure dict
  → Table Recovery dict
  → TextFlowResult
  → EvidenceReport
```

正式 runner 保留同一次 parse 中已经产生的六类共享对象，连同 `table_result`、`text_flow` 一起交给 `create_evidence_report`，完成后才释放 Native 中间引用。接口新增可选 `profile`、`snapshot_meta`、`snapshot_pages`、`section_alignment`、`page_structure`；全部传入时四个 Native artifact、Stage5 JSON、Stage6 JSON 的 Evidence runtime read 均为 **0**。meta/pages 只传一个会明确拒绝，以免无意混用对象与文件。没有重新 parse、重构等价 dict 或深拷贝整份输入。

未传对象时，旧 `run_evidence_manifest` / `create_evidence_report` 文件入口原样可用：profile、snapshot、alignment、Stage4、Stage5 和 Stage6 artifact 均可从路径独立读取。所有旧 artifact 继续以原路径、schema 和序列化方式写出，Evidence writer 未改。EvidenceReport 继续直接传给 Quality；本轮未动 Quality。

测试在真实 case_002/003/004 的对象路径精确拦截上述全部文件读操作，再独立调用旧全文件入口。两者生成相同 `EvidenceReport`，两个 Evidence JSON/Markdown artifact 逐字节相同。调用前后，完整 profile/alignment/Stage4/Table Result/TextFlowResult 值相同，snapshot 逐页原 JSONL 序列化 SHA256 相同，未发现共享对象 mutation。

## 三例 parity 与 accounting

三个真实 PDF 都重放 Profiler → Section → Page Structure → Table Recovery → TextFlow → Evidence，没有启动重型 Provider。snapshot、alignment、Stage4、Stage5 与冻结 artifact 相同；全部 Stage6 JSON/Markdown 与冻结结果逐字节相同。Evidence 跨临时目录与冻结目录仅 `inputs` 的绝对路径不同；其它全部嵌套字段相等。把 `inputs` 换成冻结路径后，Evidence JSON 的**完整字节**与冻结文件一致，覆盖 accounting、source refs、provenance、diagnostics 和 document/page refs。profile 中的 `snapshot_file` 也只随输出目录变化，字段及其它内容保持。

下表沿用冻结 Evidence `summary` 的现有口径；“表格区域/已记账”分别为 `region_type_counts.table` / `region_status_counts.ACCOUNTED_TABLE`，不是重新定义表格数量。

| Case | 有效原生 words | 已记账 | 未记账 | 比例 | 表格区域/已记账 | 已记账表格 words | final-flow words |
|---|---:|---:|---:|---:|---:|---:|---:|
| case_002 | 1,231 | 1,231 | 0 | 1.0 | 13 / 11 | 1,039 | 1 |
| case_003 | 8,864 | 8,845 | 19 | 0.997856 | 39 / 37 | 1,597 | 9 |
| case_004 | 4,010 | 4,010 | 0 | 1.0 | 17 / 15 | 1,614 | 1 |

三例的 `final_flow_accounting_completed` 均为 `true`。完整 artifact 字节 parity 同时保护每页明细和 provenance，没有改变 unresolved 或 coverage 口径。

## 测试与剩余 runtime file bus

扩展 `tests/unit/test_table_result_handoff.py` 的独立对象及 runner 连线测试，扩展 `tests/unit/test_snapshot_structure_handoff.py` 的三例真实链：验证所有对象身份、精确禁止六类文件重读、只读、旧全文件入口、Evidence artifact 字节 parity。修改前基线为 full **284 passed、20 skipped、0 failed**，reference-bound **304 passed、0 failed**。

- full：**284 passed、20 skipped、0 failed**。
- reference-bound：**304 passed、0 failed**。
- skipped：与基线相同；不设置 `PDFFAST_REFERENCE_ROOT` 时相应 reference-bound 测试跳过。

至此，正式 **Native → Evidence** 计算链中的 profile、snapshot、alignment、Stage4、Stage5 和 TextFlow artifacts 均仅作为保留的产物与兼容入口，不再是各相邻阶段继续计算的必需数据总线。已知后续仍有 Stage10/Canonical 对 normalized flow、Quality artifact、provider plan 和 selected predictions 的文件输入；runner 的审计/回归输出也继续使用 artifact。本轮未进入 Canonical 收口或扩展审计后半段。

执行命令使用 `UV_CACHE_DIR=/tmp/pdffast-r3b9-uv-cache uv run --no-sync pytest -q tests/unit tests/contracts tests/regression`；reference-bound 另设置 `PDFFAST_REFERENCE_ROOT`、`PDFFAST_SAMPLE_PDF`。`--no-sync` 使用已有 `.venv`，以避开当前沙箱对默认 uv cache 的访问限制。
