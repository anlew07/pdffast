# R3-B6 Page Structure → Table Recovery Object Handoff

日期：2026-09-30。范围仅为 Page Structure 到 Table Recovery 的 Stage4 输入交接；解析算法、Stage4/Stage5 schema、writer 与后续消费者均未改动。

## 原读取点与数据

`run_page_structure` 返回 `build_document_structure` 的 `dict`，并把**同一值**以 `json.dumps(..., ensure_ascii=False, indent=2)` 写到 `page_structure.json`。正式 runner 过去丢弃此返回值。`run_table_recovery` 在入口执行 `load_json(structure_path)`，再执行 `load_snapshot(snapshot_path)`；前者是本轮消除的 Stage4 runtime read，后者仍保留。

Table Recovery 实际消费 Stage4 的 `pages` 中的 blocks、页号、表格/无框表候选、checkbox controls、章节归属与跨页关联信息，以及顶层 `cross_page_table_candidates`、`page_count`、`source_file`。它用 snapshot JSONL 中的原生文字、words、表格候选等恢复表格；不直接读取 profile、section alignment、PDF 或配置。它没有第二个 Stage4 loader。`build_document` 对页列表使用 `sorted(...)` 生成新列表，其它所需索引和候选也构造在局部变量中；回归测试比较完整 Stage4 dict，未观察到原地修改。

## 对象交接与兼容路径

```text
Profiler profile/snapshot（内存）
  → Section Discovery alignment（内存）
  → Page Structure dict
       ├→ 原样写 Stage4 page_structure.json
       └→ Table Recovery 的 page_structure 参数
            ├→ 原样写 Stage5 result.json / result.md / logical_tables.md
            └→ 同一 table_result dict → TextFlow 与 Evidence
```

`run_table_recovery` 增加可选 `page_structure` 参数。正式 runner 把 `run_page_structure` 返回的 dict 原样传入；传入时不读取 Stage4 JSON，未传时仍按旧 `structure_path` 文件接口加载。`snapshot_path` 及其 JSONL 读取不变。Stage4 和 Stage5 artifact 继续照原路径与序列化方式写出。旧 file API 可只给 Stage4 与 snapshot 文件路径独立运行。

合成测试在对象路径拦截 Stage4 文件读取，读次数 **0**，再调用旧 file API，比较完整 Stage5 dict 及三个 Stage5 artifact 的字节；完整 Stage4 dict 调用前后相同。runner 测试确认 Stage4 writer 已写文件，且传给 Table Recovery 的对象是 writer 所用的同一实例；Table Recovery 返回的同一实例继续传给 TextFlow 和 Evidence。真实 case_002/003/004 的单条测试链还分别拦截 Stage4 → Table Recovery、Stage5 → TextFlow/Evidence 的重新读取，均未触发。

## 冻结样本 parity

三个真实 PDF 均执行 Profiler → Section Discovery → Page Structure → Table Recovery → TextFlow → Evidence，不启动重型 Provider。Stage4、Stage5 的对象/file 路径结果逐字节相同；Stage4 JSON、Stage5 `result.json`/两个 Markdown 文件，以及 Stage6 的五个 JSON 文件，均与 `outputs/final_structure_regression/<case>/` 冻结 artifact 逐字节相同。TextFlow 的完整结果含 noise、reading order、paragraphs、cross-page paragraphs 与 normalized flow。Evidence 除 `inputs` 中指向本次临时输出目录的路径外，与冻结 JSON 的所有字段和嵌套值完全相同；将这组路径替换为冻结目录路径后，完整 JSON 对象相等。路径差异是 provenance，不是解析内容变化。

| Case | Stage4 SHA256 | Stage5 result SHA256 | normalized TextFlow SHA256 | Evidence 比较 |
|---|---|---|---|---|
| case_002 | `3639575a0c5af216cf96d60b3759d64c2c0863bfc4aaae8afe499150fa3bae68` | `27bc7cc8c11650696c48c49edd973dda9edc2fd2a69a9a9bdddca9cb7c7f47a0` | `3f39802c5e38cb00780b5a3ede96cb49501b7e51791fdba` | 仅 `inputs` 路径不同 |
| case_003 | `bad02207507891bfaa4c34c25971d4df4167fb1517dbac871cd3f189c7892bff` | `d5030f69f81c4e946de6d0cfa1b4a003cc0d35c3ec18fbdaf3b1244833f4d215` | `78410b0555e4297719dff03dc4aba42c72b6e9c70ef28082fafa538290221916` | 仅 `inputs` 路径不同 |
| case_004 | `2ffe9036bf4a80a5873894ecfef13d6054670842c1dfcc5cda37d3f4a31d3018` | `962e8286d2303532c2b32ea83e4c24910c2ba5aabf061874926199db82a88287` | `80b7aed2e533ef40f232354ac85bb8fbb3b6ca2a35fedc356d826994608e3859` | 仅 `inputs` 路径不同 |

case_002 覆盖表格路径，case_003 覆盖复杂附件及大量表格恢复，case_004 覆盖长文档与编号延续。现有 `type=table` 等表格统计口径未改。

## 当前 Native 链及剩余文件读取

case_002 的真实链已经把 Profiler profile/snapshot、Section alignment、Page Structure、Table Result、TextFlow 结果以内存对象交接到各自下游；这些 artifact 仍照常旁路写出。当前尚存的 runtime artifact 读取包括：Table Recovery 的 snapshot JSONL；TextFlow 的 snapshot JSONL 与 Stage4 JSON；Evidence 的 profile JSON、snapshot JSONL、alignment JSON 与 Stage4 JSON。它们是本轮记录的后续边界，不在 R3-B6 修改范围内。后半段 pipeline 还存在各自 artifact/diagnostic 读取，本轮未审计或迁移。

## 测试

扩展 `tests/unit/test_snapshot_structure_handoff.py` 和 `tests/unit/test_table_result_handoff.py`，覆盖正式对象传递、Stage4/Stage5 写入、禁止重读、只读、文件接口、三例 Stage4/5/TextFlow/Evidence parity。修改前基线为 full **284 passed、20 skipped、0 failed**；reference-bound **304 passed、0 failed**。

- full：**284 passed、20 skipped、0 failed**。
- reference-bound：**304 passed、0 failed**。
- skipped：与基线相同，仍是未设置 `PDFFAST_REFERENCE_ROOT` 时的 reference-bound 测试跳过。

执行命令使用 `UV_CACHE_DIR=/tmp/pdffast-r3b6-uv-cache uv run --no-sync pytest -q tests/unit tests/contracts tests/regression`；reference-bound 另设置 `PDFFAST_REFERENCE_ROOT` 和 `PDFFAST_SAMPLE_PDF`。`--no-sync` 使用已有 `.venv`，以避开当前沙箱对默认 uv cache 的访问限制。
