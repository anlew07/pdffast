# PDFFast Maintainer Skill

基于 PDFFast V3 构建的专用工程维护 Skill，放在长期分支 skill/pdffast-maintainer，不合入 main。分支继承项目历史，但不自动追踪 main；项目更新后需要同步检查 Skill 合同。

安装：从分支复制 skills/pdffast-maintainer/ 到支持 Agent Skills 的目录（如 ~/.agents/skills/pdffast-maintainer/）。在实际 PDFFast 项目工作目录中启动 Agent，或给脚本指定 --project-root。无需把 Skill 并入项目主线。

自检：python scripts/selfcheck.py --project-root /path/to/pdffast
纯逻辑测试：python -m unittest discover -s tests -v
命令详情参见 SKILL.md。

第一版可执行：静态项目检查、已有 Benchmark 的 prepare/plan/execute/compare/score 编排、配对文字升级门禁、Skill 自检。技术搜索由 Agent 联网能力实施，非后台定时任务。自动生成 Adapter、完全无人介入的安装/模型下载/生产替换、真正自动创建升级 PR 仍需后续实现，当前不可宣称已具备。

首次基于 2026-11-18 核对的 main 164fc49c1a4bc305864639a4a5fc36be2f098489 构建。未在用户本机运行真实 Provider 模型。