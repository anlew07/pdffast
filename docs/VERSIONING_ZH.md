# PDFFast 命名、分支、版本与发布规范

## 1. 统一名称

| 层级 | 规范 |
|---|---|
| 产品/文档标题 | **PDFFast** |
| GitHub 仓库 | `anlew07/pdffast` |
| Python 包/导入 | `pdffast` |
| 推荐本地开发目录 | `pdffast`（路径可变，不允许硬编码私人绝对路径） |
| 主分支 | `main` |
| 旧 `v1/v2/v3` | 历史架构阶段和实验记录；不再作为新仓库/目录命名规则 |

**当前源码声明的发行版本是 `pyproject.toml` 的 `0.1.0`，不等于“V3 版本号”。** 此次文档整理不擅自提升发行版本，也不创建 Release/Tag。

HTTP 响应中的 `schema_version="1.0"` 是接口合同版本，同样不是项目发布版本。

## 2. Git 分支约定

- `main`：集成分支；通过 PR 合并，避免在本地未验证时直接覆盖。
- `fix/<topic>`：问题复现与最小 Bug 修复。
- `docs/<topic>`：文档、路径/命名和维护规范整理。
- `feat/<topic>`：明确验收的新功能；当前稳定维护阶段谨慎引入。
- `experiment/<topic>`：新 Provider/模型/策略候选验证，不应因单份 PDF PASS 直接改变默认路由。

历史 `refactor/v3`、其他阶段工作分支保留作为开发轨迹；是否清理应先确认合并情况与独有提交，不在本轮批量删除。

## 3. 版本冻结与记录

- 每个可复现的交付基线至少记录：完整 Git SHA、`pyproject.toml` 版本、根/子环境 `uv.lock`、所用 Profile、模型 revision 和必要文件哈希、平台以及测试报告。
- 如果决定对外发布新版本，先定发布策略和兼容范围，再同步更新软件版本、CHANGELOG、文档、Tag/Release；**发布前不凭当前提交自行宣称“稳定 v1.0”**。
- 模型权重通常不进入 Git：必须在单独清单固定来源与 revision，不能依赖持续变化的 Hugging Face `main`。
- 日志、人工 GT、权重和私有 PDF 不发布到公开仓库。

## 4. 变更分类与验收

| 变更 | 最低要求 |
|---|---|
| 文档/命名（不改运行时） | 链接与命令核对、保留历史、无行为改动 |
| Bug 修复 | 最小复现测试、相关单测/合同、真实用例回归（适用时） |
| Provider/模型/路由 | 包/模型 SHA、授权、preflight、单任务、真实 PDF、GT/人工复核、可回滚 |
| API/输出 Schema | 合同测试、调用方影响分析、迁移与向后兼容决策 |

PR 必须写清测试的实际 PASS/FAIL/SKIP，和仍然未验证的范围。

## 5. JudgeAI 与独立 PDFFast 解耦

JudgeAI 在自己的 `pdffast.lock.json` 中固定 PDFFast Git Commit 和隔离运行时。PDFFast `main` 的新提交，**不会自动升级 JudgeAI**；必须在 JudgeAI 依照其 `scripts/pdffast_version.py` 执行 `update <full_sha>`、环境 preflight 和真实 PDF 测试，再单独提交锁文件。

反过来，PDFFast 的新克隆或本地重命名，不应修改 JudgeAI 数据、`.runtime`、任务状态或已锁定部署。二者是独立工作区、独立 Git 变更。
