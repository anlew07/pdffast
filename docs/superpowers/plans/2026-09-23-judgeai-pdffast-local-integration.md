# JudgeAI 本机 PDFFast 接入实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让本机 JudgeAI 任务通过稳定子进程接口调用 PDFFast，保存可追踪的解析结果与质量摘要，并以真实 PDF 验证端到端流程。

**Architecture:** PDFFast Core 继续保持 transport-agnostic，并在自身包/配置资源中包含 Stage 10 实现和默认运行配置。JudgeAI 通过配置的 PDFFast Python 环境及 runner 子进程调用 Core，任务数据库记录解析状态、产物路径、审计摘要、未解析区域数与日志定位。

**Tech Stack:** Python 3.12 PDFFast、Python 3.14 JudgeAI、pytest、SQLModel、Celery、JSON 文件产物。

## Global Constraints

- 不修改 `configs/frozen/stage9_route_candidates_prod_v001.json`。
- 不修改解析阈值、Provider escalation 顺序，不下载或复制模型。
- JudgeAI 不导入 PDFFast Provider、不操作内部 Stage；只通过公开 runner 接口调用。
- 不覆盖工作区已有未提交修改；仅编辑本计划列出的接入相关文件和新增测试/文档。
- PDFFast Core 不依赖 FastAPI、Celery 或 HTTP 类型。
- 每次解析使用唯一 `run_id`；保留 `audit_status`、未解析区域数量、失败摘要及产物/日志路径。

---

### Task 1: 消除 Stage 10 对旧工程脚本的运行依赖

**Files:**
- Modify: `pdffast/canonical/builder.py`
- Modify: `pdffast/render/llm_ready.py`
- Modify: `pdffast/audit/structure_boundary.py`
- Create/Modify: `pdffast/resources/configs/*`
- Test: `tests/unit/test_phase4_core.py`
- Test: `tests/unit/test_package.py`

**Interfaces:**
- `PDFFastParser.parse(pdf_path, run_id=...)` 可在显式配置根或内置默认资源下运行。
- Stage 10 生成结果不得通过固定旧项目绝对路径导入实现。

- [ ] 将 Stage 10 参考实现纳入包内模块并保持行为等价。
- [ ] 将运行所需的 Provider、模板、Frozen Policy 配置作为包资源或显式配置提供。
- [ ] 增加隔离临时项目目录/安装产物测试，确保 Stage 10 不读取旧工程脚本。
- [ ] 运行 phase4、package、配置和相关回归测试。

### Task 2: JudgeAI 配置、自检与解析结果契约

**Files:**
- Modify: `backend/app/core/config.py`
- Modify: `backend/app/integrations/pdffast_adapter.py`
- Modify: `backend/app/integrations/pdffast_runner.py`
- Modify: `backend/app/models.py`
- Create: Alembic migration for PDFFast summary fields
- Test: `backend/tests/` PDFFast adapter and task contract tests

**Interfaces:**
- Settings provide explicit `PDFFAST_PROJECT_ROOT`, `PDFFAST_PYTHON`, and `PDFFAST_OUTPUT_ROOT` paths with validation/preflight.
- Adapter returns a validated summary with run ID, result paths, audit status, unresolved count, pipeline failures, and integration log path.
- Public task response exposes parse status and safe summary, not full document content.

- [ ] 先写配置/摘要验证的失败测试。
- [ ] 增加清晰的环境自检错误和独立日志路径。
- [ ] 数据库迁移只新增 PDFFast 解析状态/摘要字段，不改已有记录语义。
- [ ] 验证异常任务保存错误摘要及日志位置。

### Task 3: 将真实解析接入 JudgeAI Worker

**Files:**
- Modify: `backend/app/worker/tasks.py`
- Modify: `backend/app/api/routes/review_tasks.py` only if result serialization requires it
- Test: `backend/tests/` Worker integration tests

**Interfaces:**
- Worker 对已上传 PDF 调用 `run_pdffast`，传入 UUID `run_id`，再更新任务解析状态和结果摘要。
- 解析成功但审计发现未解析区域时仍记录为执行成功，同时明确质量状态，供业务侧判断。
- 解析失败时任务进入 FAILED，并记录易定位错误与日志路径。

- [ ] 增加任务调用路径测试，验证实际使用材料路径、唯一 run ID、成功/失败状态。
- [ ] 替换当前 PDF header 后的模拟等待逻辑为 PDFFast 调用。
- [ ] 保持 `simulate_failure` 的开发验证语义。
- [ ] 运行 JudgeAI 后端测试。

### Task 4: 本机真实 PDF 端到端验证

**Files:**
- Create/Modify: `docs/INTEGRATION_ZH.md` in PDFFast and/or JudgeAI integration notes
- No Frozen Policy/config mutation

- [ ] 确认两个项目的独立解释器、配置目录、共享模型 cache 和输出目录。
- [ ] 执行 JudgeAI 实际任务入口对一个本机真实 PDF 的 smoke test。
- [ ] 检查 task 状态、Markdown/JSON/audit/manifest、未解析区域、失败数和日志路径。
- [ ] 运行 PDFFast 默认测试、相关回归测试及 JudgeAI 后端测试。
- [ ] 汇报可复现的启动/调用步骤及剩余限制。
