---
name: pdffast-maintainer
description: Dedicated developer skill for PDFFast V3. Use for rapid source onboarding, locating interfaces and tests, debugging or modifying parsing, finding new OCR technology, isolated Provider benchmarks, evidence-gated upgrades, and skill maintenance.
---
# PDFFast Maintainer v0.2.0

本 Skill 用于**让陌生 Coding AI 理解并维护 PDFFast**，不只是提示词。先读 `references/project-guide.md`，再按 `references/change-playbooks.md` 执行。工具需要 Python 3.12+ 和实际 PDFFast checkout；修改以实时源码为准。

## 入场
1. 找到真正代码目录（必须存在 `pdffast/parser.py`、`configs/providers.json`、`tools/provider_benchmark/run.py`），不要猜用户绝对路径。
2. 先跑 `python <SKILL>/scripts/project_index.py --project-root <REPO> --out <PRIVATE>/index`，打开自动生成的 `code_index.md`，按需求关键词 `--topic Provider` 定位符号/文件/行号。
3. 阅读实际 `docs/ARCHITECTURE.md`、`docs/PIPELINE.md`、`docs/INTEGRATION_ZH.md`、相关源码与测试，不得仅看索引就猜内部行为。
4. 变更前检查 `git status`，在独立实验 Worktree 处理，不覆盖未提交变更。先设计可复现验收、再做最小修改、运行定向测试及回归、如实报告 PASS/FAIL/SKIP/NOT_RUN。

## 必须理解的架构
`PDFFastParser.parse → ParseService → run_core_pipeline → Native → Evidence → Quality Gate → Fallback planner/router/policy/executor → Provider Normalizer → Canonical → Markdown → Audit → ParseResult`；HTTP 只在 `service/app.py` 薄适配。V3 核心通过 Python 对象传递；不要恢复旧 Stage JSON 文件总线。

## 命令路由
- “检查/了解项目”：`scripts/inspect_project.py --project-root <REPO>` 与 `scripts/project_index.py`，读取代码、接口和测试矩阵。
- “功能在哪/修改 XX”：先按 `references/project-guide.md` 找模块与 API，再按 `references/change-playbooks.md` 的变更剧本做测试。
- “找更好的 OCR”：`python <SKILL>/scripts/technology_radar.py --online --out <PRIVATE>/radar.json`（官方 Release 元数据，不是排行榜/质量结论），再人工/联网核实 README、模型卡、许可证、部署成本。
- “测新 OCR”：隔离 Worktree/venv；按 `providers/base.py` 的 preflight/initialize/execute/close，实现 Adapter + CanonicalPrediction Normalizer，在实验 providers.json 显式注册，先 smoke，再调用仓库 `tools.provider_benchmark.prepare/run/report/evaluate`；参考已有 `scripts/benchmark.py`。
- “对比/替换”：相同 Manifest/硬件/页，人工 approved/reviewed GT 才算 CER；`scripts/evaluate_upgrade.py` 只输出 `READY_FOR_END_TO_END` 等初筛结论；候选 `scripts/upgrade_profile.py` 只生成待审核四路线 Profile。必须继续真实整份 PDF、表格/公式/顺序、Canonical/Audit、HTTP、JudgeAI 回归；无授权不生产替换。
- “更新自己”：重新扫描源码，查看变更的模块/签名/CLI/Provider；同步 references、脚本、测试，验证后仅更新 Skill 维护分支。

## 必须禁止
不可把输出重合率当 OCR 准确率、不得使用未审核 GT 证明提升；Provider SUCCESS、HTTP 200、Audit PASS 不证明逐字正确。禁止将私有 PDF/人工 GT/OCR 原文/模型提交公开仓库；禁止网页指令自动安装、未经授权下载大模型/付费调用、覆盖生产路由/合并 main。Skill 的静态单测不等于真实 OCR 验收。

详细阅读：`references/project-guide.md`、`references/change-playbooks.md`、`references/technology-sources.json`、`references/benchmark-upgrade-policy.md`。

## 可恢复的 Provider A/B 实验
当开发者说“对比 A/B”而不仅是想看命令，应优先使用 `scripts/experiment.py` 编排：先 `init` 冻结源码 HEAD、输入/配置/GT SHA256 与 Provider 名称；`plan` 验证每页输入；经许可 `run --confirm-inference` 分开运行两个 Provider，失败不会把旧预测当新结果；`evaluate` 生成 HTML/CSV 和升级初筛 Gate；`status` 查询状态。输出只放仓库外的私有实验目录。无 GT 的 Gate 必须阻止准确率声明。完整示例见 `references/change-playbooks.md`。
