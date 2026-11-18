# PDFFast 开发操作剧本

## 一、新 OCR 如何发现、验证和替换
0. **只读定位**：`inspect_project.py --project-root <REPO>` + `project_index.py --topic Provider`，核对 `main`、dirty 文件、`configs/providers.json` 六个默认 Provider 和可选插件、已有 Profile。
1. **去哪找**：运行 `technology_radar.py --online` 获取官方仓库 Release 元数据；进一步到 GitHub README、Releases、Hugging Face 模型卡、PyPI changelog、官方论文和公开 Benchmark 验证。入口详见 `technology-sources.json`。记录版本/commit、来源日期、许可证/商用限制、Python/CPU/MPS/GPU/VRAM、依赖/权重大小、离线部署方法、已知失败类型。模型宣传不当作本地质量证据。
2. **确定范围**：扫描整页文字(`PAGE_DOCUMENT_OCR`)、复杂布局(`PAGE_DOCUMENT_LAYOUT_PARSE`)、局部图像(`REGION_MULTIMODAL_PARSE`)、内联上下文(`INLINE_CONTEXT_PARSE`)分别测试。不要一个 OCR 统一替换所有路线。
3. **隔离环境**：先检查 `git status`，使用 `git worktree add -b experiment/<NAME> <PRIVATE_WORKTREE> main`，单独 `uv venv`。安装依赖及模型之前核实许可证、下载/费用/硬件并获授权，精确锁定版本；不在生产环境直接安装。
4. **源码接入**：阅读 `pdffast/providers/base.py`、`registry.py`、`runtime_normalization.py`、`normalization.py` 和 `minicpm_ocr.py/minicpm_normalizer.py` 现成插件例子。Adapter 实现 `preflight/initialize/execute/close`，返回 `RawProviderResult`；Normalizer 产出 CanonicalPrediction 全字段并通过校验。仅对实验配置 `providers` + `plugins` 显式注册，**不修改 Quality Gate/默认生产路由**。
5. **Smoke**：package import → preflight/cache 检查 → 真实单页推理 → Raw/Canonical 校验 → 超时/失败/关闭与回退。运行 `tests/unit/test_provider_plugins.py`、`test_runtime_normalization.py`、`tests/provider/test_provider_contracts.py`。
6. **同样输入做 A/B**：`tools.provider_benchmark.prepare` 按同一 PDF 页生成 PNG/raster-only PDF（默认可选 200dpi）；`run --dry-run` 检查计划，用户授权后 `run` 分别执行新旧 Provider，`report` 同页对照，`evaluate` 仅使用人工 approved/reviewed GT 算 CER。Skill 的 `scripts/benchmark.py` 封装这五步。各次记录输入 SHA、模型版本、硬件、失败/缺页、耗时；探测集/盲测集必须**按整份 PDF 分组**。无 GT 只能比较输出相似性，不能宣称更准。表格/公式/阅读顺序分别需要自己的 GT/人工验证。
7. **升级门禁**：`scripts/evaluate_upgrade.py` 使用同 Manifest 两个 Provider 的 predictions + 审核 GT，输出 `BLOCKED`/`INSUFFICIENT_EVIDENCE`/`READY_FOR_END_TO_END`，后者仅能进入下一阶段，不代表生产批准。
8. **具体改哪里**：先保留 Adapter + Normalizer + 实验 `providers.json` 插件注册，生成**待审核完整四路由** Profile（`scripts/upgrade_profile.py`）；`scripts/run_pipeline.py <PDF> --project-root . --provider-profile <PROFILE> --output-root <PRIVATE>` 跑原始完整 PDF，对照 Canonical、Markdown、Audit；回归 unit/contracts/regression/provider/HTTP/JudgeAI 锁定版本。通过后只生成变更 PR 和回滚方案，经维护者批准才切换生产；失败保留旧 Provider 和报告，不能删证据。

## 二、出现 Bug 如何按需修改
锁定错误输入 SHA、页码、run_id、异常堆栈和区域 bbox → `project_index.py --topic <符号>` → 读取入口/调用者/测试 → 先失败用例再修复 → 定向测试 → 全回归 → 真实 PDF/输出核验。例：0×0 小区域裁剪重点调查 `quality/gate.py::_render_region_rgb` 和 Fallback 输入，不能跳过区域导致无证据丢失。

## 三、公共接口变更规范
改 `PDFFastParser` 或 `ParseResult` 必须同步 `ParserConfig`、`ParseService`、HTTP adapter、docs/INTEGRATION_ZH.md 与测试；Core 不可导入 FastAPI/Celery；不写用户机绝对路径；保护私有数据；Audit PASS 不等于逐字正确。

## 四、Skill 迭代
重新索引实际 main、对比模块 SHA/符号、Provider/CLI 变化 → 更新 project-guide 与剧本/命令 → 增补测试 → 自检 → 只提交 skill/pdffast-maintainer 分支。不要自动删除测试或把一次失败推断变成永久规则。

## 五、可恢复的一键 A/B（开发者实际操作）
```bash
python <SKILL>/scripts/experiment.py init --project-root <REPO> --lab <PRIVATE>/exp01 --manifest <PRIVATE>/inputs/manifest.jsonl --baseline <OLD> --candidate <NEW> --truth <PRIVATE>/reviewed_gt.jsonl
python <SKILL>/scripts/experiment.py plan --lab <PRIVATE>/exp01
python <SKILL>/scripts/experiment.py run --lab <PRIVATE>/exp01 --confirm-inference
python <SKILL>/scripts/experiment.py evaluate --lab <PRIVATE>/exp01
python <SKILL>/scripts/experiment.py status --lab <PRIVATE>/exp01
```
Lab 必须在项目仓库外；工具保存 experiment.json、plan/run 日志、预测哈希、HTML 比较、upgrade_gate.json。状态 INIT → PLANNED → EXECUTED → EVALUATED，执行失败为 PARTIAL/BLOCKED，可在保持输入指纹不变的前提下重试。实验只做文字配对与过程证据，结果 READY_FOR_END_TO_END 必须继续整份 PDF 结构/表格/公式/阅读顺序以及服务和 JudgeAI 验收。

## 六、Skill 自更新如何防止过期
`scripts/contract_sync.py check --project-root <REPO>` 根据已接受快照比较 Provider 名单、重要源码哈希和 CLI flags；发现漂移后由 Agent 实际检查当前代码，修改 references/脚本/测试，再经 review 与完整 Skill 单测后 `contract_sync.py accept --project-root <REPO> --confirm-reviewed`。严禁一发现差异就静默接受。
