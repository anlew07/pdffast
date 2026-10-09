# R3-B4 Section Alignment → Page Structure Object Handoff

日期：2026-09-30。范围仅为 Section Discovery 到 Page Structure 的 alignment 输入交接；Section Discovery、Page Structure 的判断和生成算法均未改动。

## 原读取点与实际对象

`run_section_discovery` 返回 `discover_sections(...)` 生成的 `dict`，并将**同一个值**以 `json.dumps(result, ensure_ascii=False, indent=2)` 写到 `section_alignment.json`。正式 runner 过去丢弃返回值。`build_document_structure` 在构造页索引前调用 `load_json(aligner_path)` 重新读取它；这是 Page Structure 唯一的 alignment 文件加载点。

Page Structure 使用 alignment 的 `pages`（逐页 `section_id`、`title`、`structure_type` 等归属信息）、`page_count`、`source_file` 做结构关联与输入一致性校验；使用 `aligner_version` 和 `structure_mode` 填充输出元数据。`aligner_path` 的字符串仍写入 Stage4 `inputs.section_alignment` provenance。`page_profile.json` 仍由 `load_json(profile_path)` 读取，本轮没有迁移 profile。

## 新交接与兼容入口

```text
Profiler snapshot（内存）
  → Section Discovery 返回 alignment dict
       ├→ 原格式写 section_alignment.json
       └→ runner 直接传给 Page Structure 的 section_alignment 参数
              → 原格式写 page_structure.json
```

`build_document_structure` 与 `run_page_structure` 增加可选 `section_alignment` 参数。传入对象时直接使用该 dict；不传时照旧 `load_json(aligner_path)`。因此旧的 snapshot/profile/alignment 文件接口仍可独立工作，CLI、脚本、回归和恢复路径不受影响。正式 runner 把 Section Discovery 的返回值原样交给 Page Structure，并在 Stage4 完成后释放本次 parse 的共享引用。没有新增模型、adapter、深拷贝或算法分支。

对象路径的 Page Structure 对 alignment JSON 的运行读取为 **0**。artifact 仍按原路径、原 schema 和原序列化方式生成。后续 Evidence 仍有其既有的 alignment artifact 输入，本轮不迁移该边界。

## 只读、文件兼容与冻结 parity

合成测试拦截 snapshot/alignment 的 `Path.open` 读取，确认 Page Structure 对象路径均没有重开文件；同时允许 profile 文件读取。测试比较调用前后的完整 alignment 嵌套值与 writer 字节，未发现 mutation。旧文件接口随后独立运行，所得 Stage4 dict 和 JSON 字节均与对象路径一致。

真实 case_002/003/004 重新执行 Profiler、Section、Page Structure，没有启动 Provider。每例 Section writer 的 SHA256 与冻结 artifact 一致；新对象路径与旧文件路径 Stage4 JSON 逐字节一致。另用冻结 provenance 路径生成 Stage4，完整输出 dict 与冻结文件一致，SHA256 也一致。页数、region/block 数量和内容、ID、类型、bbox、section association、unresolved 与 diagnostics 因完整 Stage4 字节相同而保持一致。

| Case | 页数 | Stage4 blocks | Section SHA256 | Stage4 SHA256 |
|---|---:|---:|---|---|
| case_002 | 16 | 57 | `65f8657cde8fb1b4ca87ef09da4040849684ae14ba3df888dd7095d095a994a2` | `3639575a0c5af216cf96d60b3759d64c2c0863bfc4aaae8afe499150fa3bae68` |
| case_003 | 66 | 537 | `47b1859877758e0c4090c608f99759cb3cb787e3762011104a48ad530fa6268a` | `bad02207507891bfaa4c34c25971d4df4167fb1517dbac871cd3f189c7892bff` |
| case_004 | 114 | 540 | `284935ddb980f3de5340b140dc25f9bb90cdf7f775e1c36fc358d97074417e94` | `2ffe9036bf4a80a5873894ecfef13d6054670842c1dfcc5cda37d3f4a31d3018` |

case_003 的重复 Native heading 未改变结构关联。case_004 的 p25、p48、p80、p90、p101、p114 归属仍为 `observed_section_011`、`012`、`013`、`014`、`015`、`015`；p101–114 的 continuation 未改变。

## 测试结果

扩展 `tests/unit/test_snapshot_structure_handoff.py`，覆盖 runner 对象传递、alignment 写入与冻结 SHA、Page Structure 禁止重读、共享对象只读、对象/file 路径字节等价、三个真实 case 的冻结 Stage4 SHA 和既有结构断言。修改前基线为 full **284 passed、20 skipped、0 failed**；reference-bound **304 passed、0 failed**。

- full：**284 passed、20 skipped、0 failed**。
- reference-bound：**304 passed、0 failed**。
- skipped：与基线相同，仍为未设置 `PDFFAST_REFERENCE_ROOT` 时的 reference-bound 测试跳过。

使用 `UV_CACHE_DIR=/tmp/pdffast-r3b4-uv-cache uv run --no-sync pytest -q tests/unit tests/contracts tests/regression`；reference-bound 另设置 `PDFFAST_REFERENCE_ROOT` 和 `PDFFAST_SAMPLE_PDF`。`--no-sync` 使用已有 `.venv`，以适配当前沙箱内默认 uv cache 不可访问的环境。
