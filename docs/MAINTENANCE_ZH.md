# PDFFast 稳定维护手册

**适用范围**：目前项目以修复真实 Bug、提高解析稳定性、审查 OCR 质量、升级/替换 Provider 为主。该流程不授权大规模重构或更改默认路线。开始前请阅读 [AGENTS.md](../AGENTS.md)。

## 1. 接到问题先采集什么

建立最小问题记录：

| 维度 | 必填证据 |
|---|---|
| 版本 | `git rev-parse HEAD`、`git status --short` |
| 环境 | 系统架构、Python 版本、uv 版本、各 Provider 独立环境情况 |
| 输入 | PDF 文件摘要（SHA-256）、页数、是否扫描件；私有材料仅在受控路径保留 |
| 运行 | `run_id`、CLI/Python 参数、`provider_profile`（未传则注明默认） |
| 结果 | 异常堆栈、`diagnostics/logs/pipeline.log`、`result/manifest.json`、Audit |
| 预期 | 哪个页/字段/表格/区域错、正确结果是什么、是否有人工 GT |

`manifest.json` 可能在解析开始就出现，**不能当作完成信号**。不得凭日志“心跳”判定完成，也不能把 Provider SUCCESS/Audit PASS 当作内容准确。

## 2. 按责任层定位

| 症状 | 首查路径 | 排查重点 |
|---|---|---|
| Python/CLI 参数、配置错误 | `pdffast/parser.py`、`config.py`、`scripts/run_pipeline.py` | project_root、输出目录、Profile |
| 原生文字缺失、阅读顺序错 | `pdffast/native/` | 文本块、表格、原生证据 |
| 不必要 OCR / 本应 OCR 却未触发 | `pdffast/quality/`、`pdffast/fallback/router.py` | Quality Gate、路由决策 |
| 图像裁剪失败或空图 | `pdffast/fallback/planner.py` | bbox、页面坐标、DPI、像素区域 |
| 某 OCR 不可用、卡住、回退不正确 | `pdffast/providers/`、`pdffast/fallback/executor.py` | 解释器/模型、preflight、worker、超时与回退 |
| OCR 文本被错误合并/漏掉 | `pdffast/providers/runtime_normalization.py`、`pdffast/canonical/` | Raw/Canonical、来源、补充证据 |
| 标题、段落、表格顺序不对 | `pdffast/structure_reconciliation/`、`pdffast/render/` | 结构推断、正文映射 |
| 结果文件/结构审计异常 | `pdffast/pipeline/artifacts.py`、`pdffast/audit/` | 输出合同、引用、完整性 |
| HTTP 退出/取消问题 | `pdffast/service/app.py`、`pdffast/runtime.py` | Core/Service 生命周期 |

### 典型：0×0 裁剪

历史问题：原始区域可能小于一个像素，`page.crop(...).to_image(...).original.save()` 抛出 `ValueError: cannot write empty image`。相关防护位于 `pdffast/fallback/planner.py`，测试 `tests/unit/test_zero_pixel_fallback_crop.py`。

**修复准则**：保留 `source_bbox` 原始证据坐标，只调整 OCR 渲染范围并记录 `render.raster_bbox`；不要在 JudgeAI 中吞掉异常、伪造空文本成功。

## 3. Bug 修复操作标准

1. 在独立 `fix/<topic>` 分支从当前 `main` 开始；保留输入摘要、错误轨迹与配置。
2. **先写复现测试**：用能脱敏的最小 fixture/合成 PDF；若需真实私有样本，放在 Git 忽略目录，不上传原件或原始文本。
3. 修改最小责任模块；禁止“顺手”大规模重命名 Stage/API/默认路由。
4. 运行相关单测，再跑合同/回归。示例：

   ```bash
   .venv/bin/python -m pytest -q tests/unit/test_zero_pixel_fallback_crop.py
   .venv/bin/python -m pytest -q tests/unit tests/contracts tests/regression
   ```

5. 涉及真实 PDF 输出时，使用**同一份 PDF、同一 Profile、明确的两版 SHA**做 Markdown、Canonical、Audit 与耗时对比；标记人工未审核项。
6. PR 写清复现、修复、PASS/FAIL/SKIP、环境、风险和回滚提交。CI 失败时不合并。

## 4. OCR / Provider 的变更准入

注册新 OCR 的主要文件：

- Adapter：`pdffast/providers/<provider>.py`，实现 `preflight / initialize / execute / close`；
- 规范化：`pdffast/providers/<provider>_normalizer.py` 或适用的已有 Normalizer；
- 配置：`configs/providers.json` 中受信插件/Provider 声明；
- 路由实验：独立 `configs/profiles/*.json`，需覆盖四个 Capability Route；
- 检测：`tests/unit/`、`tests/provider/`，再做真实 PDF 的质量和性能基准。

先确定来源、模型授权、平台和硬件需求，再安装隔离依赖，固定可复现 revision 与哈希。通过 **import → artifact 检查 → preflight → 单任务输出规范化 → 真实 PDF → GT/人工质量复核** 后，才考虑改变生产选择。不能只看非空 OCR 文本或一个 PDF 的 PASS。

[Provider 插件合同](PROVIDER_PLUGINS_ZH.md) · [Benchmark 规范](PROVIDER_BENCHMARK_ZH.md) · [Indra Runtime](indra_runtime.md)。

## 5. 分层验收标准

| 门槛 | 能证明什么 | 不能证明什么 |
|---|---|---|
| Python import / 单测 | 可导入、局部逻辑符合合同 | 模型存在且能推理 |
| Provider 模型/哈希 preflight | 依赖与已声明资源齐备 | 真实模型输出正确 |
| Provider 单任务 | Adapter/Worker/Normalizer 协作 | 多页复杂 PDF 正确 |
| 完整 PDF Audit | 解析链路和结构合同符合审计 | OCR 逐字准确 |
| GT 及人工检查 | 被审查范围内的内容质量 | 未覆盖的全部 PDF 类型 |

测试缺失或 SKIP 应保留为 **未验**。用户级模型缓存与数据集不应被隐式当作新机天然存在。

## 6. 新开发环境的只读资源审计

`scripts/audit_environment.py` 根据当前配置检查模型路径、外部 Manifest、独立 Worker Python 路径，以及可选的模型 SHA-256。默认仅报告清单，`--strict` 在任何缺项时返回非零码，`--profile` 用于指定明确的候选组合。

```bash
.venv/bin/python scripts/audit_environment.py \
  --profile configs/profiles/production.speed.json --hashes --strict
.venv/bin/python -m pytest -q tests/unit/test_environment_audit.py tests/contracts/test_frozen_configs.py
```

仅通过静态检查不能宣称 Indra 等模型真的能运行，也无法判断 OCR 质量和许可证。更详细的迁移及删除前门禁见 [环境重建](REBUILD_ZH.md)。

## 6. 合并后的收尾

更新变更记录、当前维护文档，记录修复提交及回退路径；通知依赖 PDFFast 的系统**按各自锁文件显式升级**。JudgeAI 不在这个仓库内自动同步，其独立运行环境、数据库及任务状态不属于本仓库日常清理或重构范围。
