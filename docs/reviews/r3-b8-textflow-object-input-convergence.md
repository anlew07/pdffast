# R3-B8 TextFlow Object Input Convergence

日期：2026-09-30。范围仅为 TextFlow 的 snapshot 与 Stage4 输入来源；噪声、阅读顺序、段落、跨页段落、表格插入和标准化算法没有调整。Evidence 及后续阶段未迁移。

## 原读取点与实际字段

`create_text_flow_result` 原先先调用 `load_snapshot(snapshot_path)`，逐行读取 Stage1 JSONL 并返回 meta 与所有 `record_type="page"` 页；随后调用 `load_json(structure_path)` 读取 Stage4 JSON。Stage5 在 R3-B1 后已优先使用传入的 `table_result`，只在未传对象时读取其文件。这里没有第二套正式 TextFlow 的 snapshot/Stage4 loader。

TextFlow 使用 snapshot meta 的 `source_file` 与版本等上游信息；逐页 snapshot 的原生文字、words、字符及页面几何/候选证据用于噪声识别、阅读顺序、段落和表格最终融合。Stage4 的 `source_file`、`page_count`、逐页 blocks、区域/章节关联和布局信息用于输入校验、结构索引、阅读顺序与记录来源。它不重开 PDF，也不加载其它生产配置文件。`run_text_flow` 兼容入口仍调用同一个核心函数并保留原文件行为。

## 新输入与旧文件接口

```text
Profiler snapshot_meta + snapshot_pages（同一次扫描的内存对象） ─┐
Page Structure dict（Stage4 writer 使用的同一对象） ────────────┤
Table Recovery dict（Stage5 writer 使用的同一对象） ────────────┤
                                                            ↓
                                               create_text_flow_result
                                                            ↓
                                               原格式 Stage6 artifacts
```

`create_text_flow_result` 增加可选 `snapshot_meta`、`snapshot_pages`、`page_structure`。正式 runner 在 Table Recovery 后保留已有对象引用并一起交给 TextFlow，完成后释放这些引用。传入完整对象时，snapshot JSONL、Stage4 JSON、Stage5 JSON 的 **TextFlow runtime read 均为 0**。未传对象时，原 `snapshot_path`、`structure_path`、`table_result_path` 文件接口仍可独立运行；只传 meta 或 pages 会明确拒绝，避免静默混合对象与文件输入。

对象路径未创建第二份 snapshot/structure/table dict，也未深拷贝共享对象。测试分别比较 TextFlow 前后的 snapshot 原 JSONL 序列化 SHA256、完整 Stage4 dict 和完整 Table Result dict，均无 mutation。计算函数、Stage6 writer、路径、schema 和输出顺序均未改动。

## 三个真实 case 的 artifact parity

真实 PDF case_002/003/004 均重放 Profiler → Section Discovery → Page Structure → Table Recovery → TextFlow → Evidence；未启动重型 Provider。snapshot、Stage4、Stage5 与各自冻结 artifact 一致。全对象 TextFlow 路径禁止读取三个输入文件；随后仅凭三个旧文件路径独立重算，得到相同 `TextFlowResult`。Stage6 的全部 11 个 JSON/Markdown 文件同时与旧文件路径和冻结输出逐字节相同，覆盖 noise、reading order、paragraphs、cross-page paragraphs、normalized flow、表格记录、正文及可读 Markdown。case_002 `record_count=71`，case_003 `record_count=631`，与原 characterization 相同；这些数字只在测试中断言。

| Case | snapshot SHA256 | Stage4 SHA256 | Stage5 result SHA256 | normalized TextFlow SHA256 |
|---|---|---|---|---|
| case_002 | `f006e74c9a3c847b6d98c1a6dd09d64850355e0445f0313a9b00460e8504fee2` | `3639575a0c5af216cf96d60b3759d64c2c0863bfc4aaae8afe499150fa3bae68` | `27bc7cc8c11650696c48c49edd973dda9edc2fd2a69a9a9bdddca9cb7c7f47a0` | `3f39802c5e38cb00780b5a3ede96cb49501b7e51791fdba` |
| case_003 | `d9c2f1d77b170672ee8159a31872e7fdee004bd8a062063bb7a1776a50429dfb` | `bad02207507891bfaa4c34c25971d4df4167fb1517dbac871cd3f189c7892bff` | `d5030f69f81c4e946de6d0cfa1b4a003cc0d35c3ec18fbdaf3b1244833f4d215` | `78410b0555e4297719dff03dc4aba42c72b6e9c70ef28082fafa538290221916` |
| case_004 | `cd3aa7ee1ac428c5b1678bf408f84df08497d3feb2b3d623c18f2b0ee9263da2` | `2ffe9036bf4a80a5873894ecfef13d6054670842c1dfcc5cda37d3f4a31d3018` | `962e8286d2303532c2b32ea83e4c24910c2ba5aabf061874926199db82a88287` | `80b7aed2e533ef40f232354ac85bb8fbb3b6ca2a35fedc356d826994608e3859` |

Evidence 仍通过既有文件输入读取 profile、snapshot、alignment、Stage4；其 Stage5 与 TextFlow 输入继续使用对象。测试对 Evidence 重放确认除了本次临时目录的 `inputs` 路径外，其 JSON 与冻结结果完全相同，替换为冻结路径后文件字节相同。本轮没有修改 Evidence。

## 测试与剩余 runtime file bus

扩展 `tests/unit/test_table_result_handoff.py` 的对象身份与 runner 连线测试，并扩展 `tests/unit/test_snapshot_structure_handoff.py` 的三个真实 case：拦截 snapshot/Stage4/Stage5 读取，检查对象只读、完整文件兼容路径与全部 Stage6 artifact 字节 parity。修改前基线为 full **284 passed、20 skipped、0 failed**、reference-bound **304 passed、0 failed**。

- full：**284 passed、20 skipped、0 failed**。
- reference-bound：**304 passed、0 failed**。
- skipped：与基线相同，仍为未设置 `PDFFAST_REFERENCE_ROOT` 时 reference-bound 测试跳过。

当前已知剩余 Native runtime file bus：Evidence 读取 profile JSON、snapshot JSONL、alignment JSON 和 Stage4 JSON。TextFlow 的三个正式输入已是对象；Stage6 artifacts 继续生成供回归、诊断与兼容接口使用。本轮未进入 Evidence convergence。

执行命令使用 `UV_CACHE_DIR=/tmp/pdffast-r3b8-uv-cache uv run --no-sync pytest -q tests/unit tests/contracts tests/regression`；reference-bound 另设置 `PDFFAST_REFERENCE_ROOT`、`PDFFAST_SAMPLE_PDF`。`--no-sync` 使用已有 `.venv`，以避开当前沙箱对默认 uv cache 的访问限制。
