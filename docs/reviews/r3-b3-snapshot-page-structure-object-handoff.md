# R3-B3 Native Snapshot → Page Structure Object Handoff

日期：2026-09-30。范围只包括 Profiler 的原生 snapshot 到 Page Structure 的传递；Section、Structure 的判断算法以及后续 Native/Provider/Canonical 流程均未改变。

## 1. 原运行依赖与完整输入

正式 runner 原先在 Section Discovery 后释放 R3-B2 收集的 `snapshot_pages`，调用 `run_page_structure(snapshot_path, profile_path, alignment_path, output_path)`。`build_document_structure` 先检查 snapshot 文件存在，再以 `snapshot_path.open("r")`、`read_snapshot_meta`、`iter_snapshot_pages` 逐页读取本次 parse 刚写出的 JSONL（`pdffast/native/structure.py:3922-4049` 的原路径）。这是 Profiler → Page Structure 的 runtime file bus。

Page Structure 同时读取 `page_profile.json` 与 `section_alignment.json`，用 profile 的逐页属性和 Section 的页面归属构造 structure blocks、表格/图像/文本/向量候选与诊断。它不重开 PDF，也不消费 Table Recovery 结果。本轮**只替换 snapshot 输入**；profile 与 section alignment 的文件读取仍保留。

## 2. 新对象链、文件接口与生命周期

```text
Profiler 的同一次 PDF page loop
  ├→ 原样写 page_snapshot.jsonl（meta + page records）
  ├→ snapshot_meta（已有 meta 字段的内存值）
  └→ snapshot_pages[page_number]（与 writer 使用的同一页 dict）
       ├→ Generic Section Discovery
       └→ Page Structure
              → 原样写 page_structure.json
```

Profiler 仅增加可选 `snapshot_meta` 收集参数；R3-B2 的 `snapshot_pages` 收集方式和 JSONL writer 不变。runner 在 Section 后保留同一份 `snapshot_pages`，把它连同 `snapshot_meta` 传给 Structure，完成后才释放两个引用。没有重建、重新解析或深拷贝 snapshot。

`build_document_structure` / `run_page_structure` 接受成对的可选 `snapshot_meta`、`snapshot_pages`。对象路径直接遍历 dict 的页值；没有读取甚至不要求 snapshot 文件存在，`snapshot_path` 仍用于历史 Artifact 的 `inputs.raw_evidence` provenance。两项都不传时，原 file API 保留原有的存在性检查、meta 读取和逐页流式 JSONL 解析；只传一项会明确拒绝，避免无意回退到文件路径。Structure 的 profile/alignment 文件加载、校验、计算和 JSON 序列化保持原样。

Section 和 Structure 的共享输入按只读方式使用。合成测试比较调用前后的完整嵌套 dict；真实样本把内存 meta+pages 按原 JSONL 序列化方式计算 SHA256，在 Section 后和 Structure 后分别核对，均与 writer 文件相同。没有观察到共享 snapshot mutation。

## 3. 真实样本及 Artifact parity

重新运行 `/Users/admin/Workspace/pdffast/benchmark/samples/real/` 的三个 PDF，仅执行 Profiler、Section Discovery、Page Structure；未启动重型 Provider。每例都在对象路径拦截 snapshot 文件读操作，读次数 **0**；随后单独执行旧 file API。两条路径的 Page Structure JSON **逐字节一致**。再使用冻结运行的原 profile/alignment 路径作为 provenance 重建 Stage4，所得 JSON 与冻结 `outputs/final_structure_regression/<case>/04_stage4/page_structure.json` 的 **SHA256 相同**，因此 region IDs/types、bbox、text refs、阅读结构字段、诊断和 section associations 均保持一致。

| Case | 页数 | Stage4 blocks | snapshot JSONL 对冻结基线 | Stage4 对冻结基线 | 对象/file 路径 |
|---|---:|---:|---|---|---|
| case_002 | 16 | 57 | SHA256 相同 | SHA256 相同 | 字节相同 |
| case_003 | 66 | 537 | SHA256 相同 | SHA256 相同 | 字节相同 |
| case_004 | 114 | 540 | SHA256 相同 | SHA256 相同 | 字节相同 |

case_004 的 p25、p48、p80、p90、p101 与 p114 的 `document_structure` 均与冻结结果相等；p101 和 p114 继续归属 `observed_section_015`。这同时覆盖编号重启和 p101–114 的章节延续。snapshot JSONL 的路径、meta/page 顺序、字段和字节未改变。

## 4. 测试与后续边界

- 新增 `tests/unit/test_snapshot_structure_handoff.py`：验证共享对象经过 Section 后仍完整；Section/Structure 不修改输入；缺失 JSONL 时 Structure 对象路径可运行；文件兼容入口可独立运行且输出逐字节相等；runner 将同一份逐页 dict 传给两个消费者。Reference-bound 用 case_002/003/004 冻结 snapshot SHA、完整 Stage4 `pages` 内容摘要和 case_004 归属。
- 修改前：full **282 passed、17 skipped、0 failed**；reference-bound **299 passed、0 failed**。
- 修改后：full **284 passed、20 skipped、0 failed**；reference-bound **304 passed、0 failed**。新增的 3 个 skipped 是真实 case_002/003/004 测试在未设置 `PDFFAST_REFERENCE_ROOT` 时正常跳过。
- 执行命令为 `UV_CACHE_DIR=/tmp/pdffast-r3b3-uv-cache uv run --no-sync pytest -q tests/unit tests/contracts tests/regression`；reference-bound 另设置 `PDFFAST_REFERENCE_ROOT` 与 `PDFFAST_SAMPLE_PDF`。`--no-sync` 使用已有 `.venv`，避开当前沙箱对默认 uv cache 的访问限制。

本轮之后，Page Structure 已不把 snapshot JSONL 当成运行输入；Table Recovery、TextFlow、Evidence 仍可能读取它。本轮没有迁移这些消费者，也没有改动 Stage4 输出 schema 或其他 Artifact 名称。
