# PDFFast — AI / 开发人员快速接手规则

## 项目目标与约束

PDFFast 是独立的 Python PDF 解析项目；正式仓库叫 `pdffast`。现阶段以 Bug 修复、Provider/模型维护、质量回归和运行稳定性为主。除非有明确需求与验收依据，**不要重构全链路、重命名公共 API、重排 Stage 或修改默认路由**。

本文件是代码导航与操作规范，不代替源码。出现分歧时以指定 Git 提交下的实际函数、配置和测试为准，避免沿用旧 V2/V3 文档中的历史路径。

## 首先查看的源码

| 问题 | 入口 |
|---|---|
| 公共 Python 解析 API | `pdffast/parser.py`、`pdffast/result.py`、`pdffast/config.py` |
| 解析主流程 | `pdffast/application/parse_service.py`、`pdffast/pipeline/runner.py` |
| 原生文本、表格、阅读流 | `pdffast/native/` |
| 来源证据与质量路由 | `pdffast/quality/` |
| OCR 区域规划及裁剪图 | `pdffast/fallback/planner.py` |
| 能力路由、候选策略、执行与回退 | `pdffast/fallback/router.py`、`policy.py`、`executor.py` |
| Provider 插件加载、配置预检 | `pdffast/providers/registry.py`、`base.py` |
| 具体 OCR / Worker 适配器 | `pdffast/providers/rapidocr.py`、`paddleocr.py`、`mineru.py`、`marker.py`、`docling.py`、`indra.py` |
| Raw → Canonical Prediction | `pdffast/providers/runtime_normalization.py`、各 Provider Normalizer |
| Canonical、文档结构、Markdown、Audit | `pdffast/canonical/`、`structure_reconciliation/`、`render/`、`audit/` |
| CLI / HTTP | `scripts/run_pipeline.py`、`pdffast/service/app.py` |
| 运行时注册和路由 | `configs/providers.json`、`configs/profiles/` |
| 模型安装与 Indra 验证 | `scripts/install_indra_runtime.sh`、`scripts/verify_indra_runtime.py` |
| 回归测试 | `tests/unit/`、`tests/contracts/`、`tests/regression/`、`tests/provider/` |

## 每次修改都要遵循

1. **先复现**：记录 Git SHA、平台、Python、配置/Profile、输入 PDF 的 SHA-256、run_id、失败日志和确切预期。私有 PDF 不上传公开仓库。
2. **确定归属**：输入/原生解析、证据与 Quality Gate、裁剪、路由、Provider、Normalizer、Canonical、Renderer、Audit 分开定位。不要通过忽略下游错误掩盖上游数据丢失。
3. **最小补丁**：保持 `PDFFastParser.parse()`、`ParseResult`、稳定 `result/` 文件契约；除非另有明确兼容方案，不改默认候选路由。不要把业务侧 JudgeAI 代码复制进 PDFFast Core。
4. **提供回归**：先添失败样例/测试，再修改；至少运行涉及模块的单测和合同测试，影响解析质量时补真实 PDF 的前后对比。
5. **不混淆通过标准**：单测 PASS、Provider accepted、Audit PASS 分别记录；OCR 内容准确性需人工核对或有权使用的 Ground Truth。
6. **可回滚**：在分支提交并经 PR 审核，记录变更的 Commit、受影响模型/Profile、测试证据。不要直接覆写部署系统的模型或 JudgeAI 的版本锁。

## 常用命令（仓库根目录）

```bash
uv sync --frozen --python 3.12 --extra dev --extra service --extra runtime-main
.venv/bin/python -m pytest -q tests/unit tests/contracts tests/regression
.venv/bin/python scripts/run_pipeline.py /absolute/path/sample.pdf \
  --project-root . --output-root outputs --run-id debug_001
```

第二条部分回归测试依赖本地外部样本或参考环境，可能 SKIP；不要把 SKIP 写成已验收。模型与 Worker 未准备好时，第三条不能保证成功。

## 环境及模型文件检查（只读）

```bash
.venv/bin/python scripts/audit_environment.py
.venv/bin/python scripts/audit_environment.py --profile configs/profiles/production.speed.json --hashes --strict
```

默认覆盖所有 `runtime_enabled` Provider；指定 Profile 时只检查该组合。缺失模型时默认清单模式退出码仍是 0（报告会标为 `MISSING_OR_INVALID`）；把 `--strict` 用作验收门禁。此工具不证明实际模型能加载/推理。

## Provider 新增或替换

阅读 `docs/PROVIDER_PLUGINS_ZH.md` 和 `docs/MAINTENANCE_ZH.md`：新适配器必须符合 `preflight / initialize / execute / close`、Raw 与 Canonical 合同；通过可信本地配置显式注册，并以 **独立 Profile** 做候选实验。比较速度、失败回退、OCR 质量、表格、结构证据与模型许可；未验收前不要替换默认路线。

Indra 的模型安装、revision、哈希及独立 Worker 见 `docs/indra_runtime.md`。它不是默认路由的自动热切换。

## 文档与数据安全

- 正式入口：`README.md`、`docs/INDEX.md`、`docs/QUICKSTART_ZH.md`、`docs/REBUILD_ZH.md`、`docs/MAINTENANCE_ZH.md`。
- 旧 V2/V3 报告保留为历史证据，不能把旧路径当成现行安装步骤。
- 不提交 `.venv`、模型权重、HF/Paddle 缓存、业务 PDF、保密日志或输出结果。
- **不得在尚未完成独立环境重建与回归前删除本机旧目录/缓存**；JudgeAI 的 `.runtime/pdffast` 是独立版本锁，不属于本项目清理范围。

完成 PR 前附：变更范围、复现步骤、执行过的测试与 PASS/SKIP、已知未验项、回滚方式。参阅 `docs/MAINTENANCE_ZH.md`。
