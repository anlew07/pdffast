# PDFFast Maintainer v0.2.0

**独立长期维护分支：** `skill/pdffast-maintainer`，不合并到 `main`。项目代码仍在自己的 main/特性 Worktree 中修改。任意可读取 Skill 文件、执行 Python 的 Coding AI 都可使用本目录（也可复制到 `~/.agents/skills/pdffast-maintainer`）。

## 开发人员快速入场
```bash
python <SKILL>/scripts/inspect_project.py --project-root <REPO>
python <SKILL>/scripts/project_index.py --project-root <REPO> --out <PRIVATE>/code-index
python <SKILL>/scripts/project_index.py --project-root <REPO> --topic Normalizer
python <SKILL>/scripts/technology_radar.py --online --out <PRIVATE>/radar.json
```
读 `references/project-guide.md` 掌握代码架构、接口和修改/测试矩阵；读 `references/change-playbooks.md` 执行 OCR 接入、Benchmark、升级、Bug 修复；`SKILL.md` 规定自动化边界。

现有 `scripts/benchmark.py` 编排 PDFFast 的 prepare/plan/execute/compare/score，`scripts/evaluate_upgrade.py` 提供配对 CER 门禁，`scripts/upgrade_profile.py` 创建**待审核**四路线候选档。未运行真实模型，不得称通过真实准确率验收。发现新 OCR 不自动安装或生产切换；复杂环境依照官方文档与授权逐步执行。
