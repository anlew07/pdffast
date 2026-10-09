# R3-B7 Snapshot → Table Recovery Object Handoff

日期：2026-09-30。范围仅为 Profiler snapshot 到 Table Recovery 的输入交接；Table Recovery 的计算、Stage5 writer、TextFlow、Evidence 和后续解析行为均未改变。

## 原读取点与实际数据

`pdffast/native/tables.py` 的 `run_table_recovery` 原先在入口调用 `load_snapshot(snapshot_path)`，以文本模式逐行读取整个 Stage1 JSONL。loader 仅保留 `record_type="page"` 的记录，按 `page_number` 建立 `dict[int, dict]`；meta 记录被忽略。它是 Table Recovery 在本轮边界的唯一 snapshot loader。

表格计算按 Stage4 `pages` 遍历，但要从对应 snapshot 页取原生 `native_text`、`words`、`table_candidates`、页高等证据，处理文本归属、候选表、边界溢出与跨页行关系。它需要全页索引以查询相邻页面，不消费 JSONL meta。Stage4 已在 R3-B6 通过 `page_structure` dict 输入；过去 Table Recovery 同时使用 **Stage4 对象 + snapshot 文件**。

## 新交接与兼容路径

Profiler 已在同一次 PDF 扫描中收集 `snapshot_pages: dict[int, dict]`，其中的页值也是 snapshot JSONL writer 写出的原始页值。`run_table_recovery` 新增可选 `snapshot_pages` 参数；正式 runner 将这份已经用于 Section Discovery 和 Page Structure 的同一个 dict 继续传给 Table Recovery。它与 `page_structure` 同时作为内存对象输入。Stage5 完成后 runner 才释放这两个共享引用。

传入 `snapshot_pages` 时，Table Recovery 不调用 JSONL loader；未传时旧 `snapshot_path` 文件接口照常独立工作，并且仍可只提供 Stage4 与 snapshot 文件完成恢复。没有新增模型、第二份 snapshot 或整份深拷贝。snapshot meta 不传给 Table Recovery，因为现有 loader 本来就忽略它。Profiler 的 JSONL writer、路径、schema、字段与顺序均未修改。

测试对正式对象路径同时拦截 Stage4 JSON 和 snapshot JSONL 的读取：两者在 **Table Recovery 内均为 0 次**。同一测试比较 Table Recovery 前后完整共享 snapshot：合成页深度相等，真实 case 的原 JSONL 序列化 SHA256 相等；没有观察到 mutation。随后独立运行旧文件入口，Stage5 dict 和全部三个 Stage5 artifact 与对象入口逐字节相同。

## case_002/003/004 parity

三例真实 PDF 均重跑 Profiler → Section Discovery → Page Structure → Table Recovery，不启动重型 Provider。snapshot JSONL 与冻结 SHA256 相同，Stage4 与冻结 SHA256 相同，Stage5 的 `result.json`、`result.md`、`logical_tables.md` 与冻结文件逐字节相同。测试还继续重放 TextFlow 与 Evidence：Stage6 五个 JSON 均与冻结文件逐字节相同；Evidence 除 `inputs` 内本次临时目录路径外完全相同，替换为冻结路径后 JSON 字节相同。

| Case | snapshot SHA256 | Stage4 SHA256 | Stage5 result SHA256 | 下游 |
|---|---|---|---|---|
| case_002 | `f006e74c9a3c847b6d98c1a6dd09d64850355e0445f0313a9b00460e8504fee2` | `3639575a0c5af216cf96d60b3759d64c2c0863bfc4aaae8afe499150fa3bae68` | `27bc7cc8c11650696c48c49edd973dda9edc2fd2a69a9a9bdddca9cb7c7f47a0` | TextFlow 字节相同；Evidence 仅路径不同 |
| case_003 | `d9c2f1d77b170672ee8159a31872e7fdee004bd8a062063bb7a1776a50429dfb` | `bad02207507891bfaa4c34c25971d4df4167fb1517dbac871cd3f189c7892bff` | `d5030f69f81c4e946de6d0cfa1b4a003cc0d35c3ec18fbdaf3b1244833f4d215` | TextFlow 字节相同；Evidence 仅路径不同 |
| case_004 | `cd3aa7ee1ac428c5b1678bf408f84df08497d3feb2b3d623c18f2b0ee9263da2` | `2ffe9036bf4a80a5873894ecfef13d6054670842c1dfcc5cda37d3f4a31d3018` | `962e8286d2303532c2b32ea83e4c24910c2ba5aabf061874926199db82a88287` | TextFlow 字节相同；Evidence 仅路径不同 |

## 测试与剩余文件输入

扩展 `tests/unit/test_snapshot_structure_handoff.py` 的合成与真实 case 测试，以及 `tests/unit/test_table_result_handoff.py` 的 runner 连线测试：确认传入的是同一份 Profiler 页 dict、artifact 仍写入、Stage4/snapshot 都未重读、对象保持只读、对象/文件接口 parity。修改前冻结基线为 full **284 passed、20 skipped、0 failed**，reference-bound **304 passed、0 failed**。

- full：**284 passed、20 skipped、0 failed**。
- reference-bound：**304 passed、0 failed**。
- skipped：与基线相同，仍为未设置 `PDFFAST_REFERENCE_ROOT` 时的 reference-bound 测试跳过。

R3-B7 后，Table Recovery 不再从 Stage4 或 snapshot artifact 取得正式运行输入。已知剩余 Native runtime file bus：TextFlow 读取 snapshot JSONL 与 Stage4 JSON；Evidence 读取 profile、snapshot、alignment、Stage4。Stage5 仍通过对象传给 TextFlow/Evidence。本轮不迁移这些剩余边界。

执行命令使用 `UV_CACHE_DIR=/tmp/pdffast-r3b7-uv-cache uv run --no-sync pytest -q tests/unit tests/contracts tests/regression`；reference-bound 另设置 `PDFFAST_REFERENCE_ROOT`、`PDFFAST_SAMPLE_PDF`。`--no-sync` 使用已有 `.venv`，以避开当前沙箱对默认 uv cache 的访问限制。
