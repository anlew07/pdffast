# R3-B5 Profiler Profile → Page Structure Object Handoff

日期：2026-09-30。范围仅为 Profiler 到 Page Structure 的 profile 输入交接；不改 Profiler、Section Discovery 或 Page Structure 的解析算法，也不迁移 Stage4 → Table Recovery。

## 原数据与读取点

`run_profiler` 返回 `scan_and_profile_pdf` 生成的 `dict`。它把**同一个 dict**经 `json.dumps(result, ensure_ascii=False, indent=2)` 写入 `page_profile.json`，然后返回给 runner。runner 在 R3-B2 后已将此对象直接交给 Section Discovery；Page Structure 却仍在 `build_document_structure` 开头 `load_json(profile_path)`，重新读取刚写出的 profile artifact。该处是 Page Structure 唯一的 profile loader。

Page Structure 使用 profile `pages` 中的页面分类、尺寸、列布局、字符数、图像和向量统计等字段，使用 `page_count`、`source_file` 做输入一致性校验，并将 `profiler_version` 写入上游版本元数据。`profile_path` 的字符串仍作为 Stage4 `inputs.page_profile` provenance。

## 新交接与兼容接口

```text
Profiler 同一次扫描
  ├→ 原格式写 page_profile.json / page_snapshot.jsonl
  └→ 返回 profile dict ────────────────┐
       snapshot meta/pages（内存） ────┤
Section Discovery 返回 alignment dict ┤
                                      ↓
                              Page Structure
                                → 原格式写 page_structure.json
```

`build_document_structure` 和 `run_page_structure` 增加可选 `profile` 参数。传入时直接消费原 dict，不调用 profile loader；未传时保留 `load_json(profile_path)`。正式 runner 将已有的 `profile` 原样传给 Page Structure。文件兼容接口仍能只依靠 snapshot、profile、alignment 路径独立构造 Stage4；writer、字段、顺序和序列化均未改动。

对象路径的 Page Structure 对 profile JSON 的 runtime read 为 **0**。同一测试还拦截 snapshot/alignment JSONL/JSON 读取，确认前几个对象交接继续有效。完整嵌套 profile 在调用前后相等，writer 字节亦相等；Page Structure 没有修改共享 profile，也没有深拷贝整份对象。

## Artifact 与真实样本 parity

重新执行 case_002/003/004 的 Profiler、Section Discovery、Page Structure，未启动 Provider。snapshot 和 alignment 与冻结 artifact 的 SHA256 相同；全对象 Stage4 与旧全文件接口输出逐字节相同。用冻结路径作为 Stage4 provenance 再生成完整 Stage4，三例都与冻结文件的完整 dict 和 SHA256 相同。页数、regions/blocks、bbox、ID、章节关联、诊断、case_003 复杂附件和重复 heading，以及 case_004 p25/p48/p80/p90/p101 与 p101–114 continuation 均受完整 Stage4 字节 parity 保护。

profile 的新临时运行与冻结输出有一个**预期的路径 provenance 差异**：顶层 `snapshot_file` 分别是本次临时 JSONL 路径与冻结目录 JSONL 路径。三个 case 的其它顶层及逐页字段完全一致。测试确认当前 profile writer 的字节等于返回 dict 的原序列化；仅将该字段换成冻结目录路径后，profile SHA256 与冻结文件相同。生产 profile schema/serialization 没有变化；不能把不同输出目录的原始 profile SHA 直接比较成相同。

| Case | 页数 | profile 冻结路径 SHA256 | snapshot SHA256 | alignment SHA256 | Stage4 SHA256 |
|---|---:|---|---|---|---|
| case_002 | 16 | `027698de675c587becfdf830f388dfb5c002b755f34583ade531a8aed300a8be` | `f006e74c9a3c847b6d98c1a6dd09d64850355e0445f0313a9b00460e8504fee2` | `65f8657cde8fb1b4ca87ef09da4040849684ae14ba3df888dd7095d095a994a2` | `3639575a0c5af216cf96d60b3759d64c2c0863bfc4aaae8afe499150fa3bae68` |
| case_003 | 66 | `1ed6b8ae7e58a03b17cca38162efe195ea686915b48bec8c28b0e067b68fe022` | `d9c2f1d77b170672ee8159a31872e7fdee004bd8a062063bb7a1776a50429dfb` | `47b1859877758e0c4090c608f99759cb3cb787e3762011104a48ad530fa6268a` | `bad02207507891bfaa4c34c25971d4df4167fb1517dbac871cd3f189c7892bff` |
| case_004 | 114 | `a8b7f1cf3a9ef884b8ea9a5514a76b67469fe460a72eaf19d2fd4a3ed3d27012` | `cd3aa7ee1ac428c5b1678bf408f84df08497d3feb2b3d623c18f2b0ee9263da2` | `284935ddb980f3de5340b140dc25f9bb90cdf7f775e1c36fc358d97074417e94` | `2ffe9036bf4a80a5873894ecfef13d6054670842c1dfcc5cda37d3f4a31d3018` |

## 测试

扩展 `tests/unit/test_snapshot_structure_handoff.py`：runner 传递同一 profile 对象；合成样本拦截 profile/snapshot/alignment 读取并检查只读与文件兼容；真实样本对 profile writer、冻结路径 SHA、对象/file Stage4 字节、冻结 Stage4 SHA 及原结构断言进行验证。修改前基线为 full **284 passed、20 skipped、0 failed**，reference-bound **304 passed、0 failed**。

- full：**284 passed、20 skipped、0 failed**。
- reference-bound：**304 passed、0 failed**。
- skipped：与基线相同；未设置 `PDFFAST_REFERENCE_ROOT` 时，依赖真实 reference 的测试按原条件跳过。

执行命令使用 `UV_CACHE_DIR=/tmp/pdffast-r3b5-uv-cache uv run --no-sync pytest -q tests/unit tests/contracts tests/regression`；reference-bound 另设置 `PDFFAST_REFERENCE_ROOT` 与 `PDFFAST_SAMPLE_PDF`。`--no-sync` 使用现有 `.venv` 以绕开当前沙箱内默认 uv cache 的访问限制。
