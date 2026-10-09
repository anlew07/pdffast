# R3-B2 Native Snapshot → Section Discovery Object Handoff

日期：2026-09-30。范围仅是 Profiler → Generic Section Discovery 的输入传递。没有修改 Profiler 的 PDF 观察/分类、Section 的 heading/ownership 算法、其他 snapshot 消费者或输出目录名称。

## 原路径与实际内存结构

- Profiler 的 `scan_and_profile_pdf` 在一次 `pdfplumber.open` 的 page loop 中，逐页得到 `capture_page_evidence(...)` 的 `dict`（`record_type=page`、`page_number`、原生文本、words/chars、几何对象、table candidates 等）。此前它随即把该 `dict` 写成 JSONL，只在内存里保留 page profile 列表；`run_profiler` 返回 profile `dict`。
- 生产 runner 随后调用 `run_section_discovery`，后者从 `page_profile.json` 读取 source/page count，再用 `load_snapshot_pages(snapshot_path)` 重读刚写出的完整 JSONL，构造 `dict[int, dict]`，调用已有的 `discover_sections(...)`。原重读点是 `pdffast/native/sections.py` 的 `run_section_discovery`。
- `discover_sections` 本来就是以 `source_file`、`page_count`、`snapshot_pages` 计算 sections、页面归属和 unresolved 的对象核心；本轮没有触碰其中任何判断。

## 新传递链与兼容性

```text
PDF page scan
  → 同一份 page evidence dict
      ├→ 原样序列化到 01_stage1/page_snapshot.jsonl
      └→ 可选 snapshot_pages[page_number]
  → run_profiler 返回原有 profile dict
  → runner 将 profile + snapshot_pages 传给 run_section_discovery
  → 原有 discover_sections 算法
  → 原样写 03_stage3/section_alignment.json
```

`scan_and_profile_pdf` / `run_profiler` 增加一个可选的 `snapshot_pages` 收集参数；默认返回值和文件行为保持原样。runner 只在这条调用里传入新建的空字典，Section 结束后立即释放该引用，避免把整份 page evidence 保留到后续 Provider 阶段。`run_section_discovery` 增加可选 `profile` 和 `snapshot_pages` 输入；二者缺省时仍按原 API 读取 profile JSON 与 snapshot JSONL。因此现有 CLI、脚本、回归测试和历史文件入口继续工作。

在正式 runner 路径，Section 不打开 snapshot JSONL，也不重读 profile JSON。**snapshot JSONL 仍按原路径、字段、页面顺序和序列化方式生成。** 它对 Section 已是旁路文件，但 Page Structure、Table Recovery、TextFlow 和 Evidence 当前仍读取它；本轮没有迁移这些边界，不能把该文件整体称作仅供观察的 sidecar。

## 对象与文件路径的验证

单元测试覆盖：Profiler 用同一页 `dict` 写 JSONL 并交给收集器；禁止 Section 读取 snapshot 文件时对象路径照常计算；旧 file API 与对象 API 产生逐字节相同的 section JSON；runner 把 Profiler 返回的 profile 和 snapshot pages 原对象传给 Section，并继续留下 JSONL Artifact。

真实 PDF 验证采用 `/Users/admin/Workspace/pdffast/benchmark/samples/real/` 中的 case_002、case_003、case_004，重新执行 Profiler 与 Section，不启动重型 Provider。改动前先以原 file API 和现有冻结输出记录 snapshot、section 及两类诊断基线；改动后比较新对象路径和旧 file API：

| Case | PDF 页 | Sections | Unresolved 页段 | Snapshot JSONL | Section JSON | Candidate / ownership diagnostics |
|---|---:|---:|---|---|---|---|
| case_002 | 16 | 10 | 1 | 与冻结基线 SHA256 相同 | 与改前 file API 字节相同 | 完全相同 |
| case_003 | 66 | 16 | 1、21–23、25–27、29–64、66 | 相同 | 相同 | 完全相同 |
| case_004 | 114 | 15 | 1、21–24 | 相同 | 相同 | 完全相同 |

case_003 的同名“关于国家自然科学基金资助项目批准及有关事项的通知”继续分别锚定 p19、p20、p24，没有按标题去重。case_004 的 p25、p48、p80、p90、p101 编号重启仍在，p101 章节继续覆盖到 p114。Section ID、标题、锚点、页范围、unresolved、候选诊断和页面归属诊断均与改前相同。对每个 case 的对象路径设置 snapshot 文件读拦截，Section 期间读次数为 0；随后单独运行旧 file API，结果和写出的 JSON 与对象路径完全一致。

## 测试与边界

- 改前冻结基线：无 reference **280 passed、15 skipped、0 failed**；reference-bound **295 passed、0 failed**。
- 改后完整测试：**282 passed、17 skipped、0 failed**。增加的两个 skip 是 case_003/004 真实样本回归在未设置 `PDFFAST_REFERENCE_ROOT` 时正常跳过。
- 改后 reference-bound：**299 passed、0 failed**。
- 命令使用 `UV_CACHE_DIR=/tmp/pdffast-r3b2-uv-cache uv run --no-sync pytest -q tests/unit tests/contracts tests/regression`，reference-bound 另设置 `PDFFAST_REFERENCE_ROOT` 与 `PDFFAST_SAMPLE_PDF`。`--no-sync` 使用现有 `.venv`，避免当前沙箱无权访问默认 uv cache。

本轮仅完成 Profiler → Section Discovery。Page Structure 等后续消费者依旧读取 snapshot JSONL；此事实是下一阶段的边界信息，不在本轮修改。
