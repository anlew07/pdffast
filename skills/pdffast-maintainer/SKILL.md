---
name: pdffast-maintainer
description: Dedicated engineering skill for maintaining PDFFast V3; inspect its code, discover better OCR or document parsing technology, run isolated Provider benchmarks, compare verified results, gate upgrades, and keep the skill aligned with the project's main branch.
---

# PDFFast Maintainer v0.1.0

目标：以 PDFFast V3 现有 Provider 插件和 Benchmark 为基础，让 Agent 可复现地检查、比较、升级和维护项目。本 Skill 在独立分支维护，不合入 main。

## 每次任务启动

1. 查找真实项目根目录：必须有 pdffast/、configs/providers.json、tools/provider_benchmark/run.py。不得根据旧对话硬编码用户路径。
2. 运行 python <SKILL_DIR>/scripts/inspect_project.py --project-root <PROJECT_ROOT>，查看当前 HEAD、dirty 文件、Registry、Profile；读取 README.md 和 docs/PROVIDER_PLUGINS_ZH.md、docs/PROVIDER_BENCHMARK_ZH.md。
3. 若当前项目版本/CLI 与 references/repo-contract.md 不符，先核实源码、更新 Skill 引用与测试。不能把参考快照当实时事实。
4. 保护未提交变更、主线和私有业务数据，禁止自动强推、覆盖配置或提交 PDF/OCR 原文。

## 意图与操作

- “检查 PDFFast”：只读库存/配置/CLI 检测；报告有证据的问题，不安装模型。
- “搜索更好的 OCR”：使用可用的联网检索能力查找官方文档/Release/GitHub/许可证，记录来源、发布日期、目标硬件、模型大小、活跃度；按四条 capability route 说明候选价值。不能只看公开榜单排名就宣称更好。
- “安装候选试试”：先新建隔离 Worktree/venv、锁定版本、检查授权/下载体积/许可证；按 Provider Adapter + CanonicalPrediction Normalizer 合同接入。只在实验配置登记，不改正式生产链。安装、模型下载及付费请求要得到相应授权。
- “和原来比一比”：先冻结相同页面输入和 commit，调用本仓库 benchmark 工具。运行前执行 plan，得到许可后 execute；compare 可在无 GT 时分析相似度，score 仅对人工 reviewed/approved GT 计算 CER。
- “把更好的替换掉”：调用 evaluate_upgrade.py 做配对初筛；通过只表示可以进入整份 PDF 端到端回归，不代表准入。单独验证表格、公式、阅读顺序、关键字段、Canonical、Audit、HTTP、回退及 JudgeAI 锁定版本；经过维护者确认才修改候选 Profile/创建 PR。
- “更新你自己”：检查 main 的变化，修改参考文件/脚本/行为测试，执行 selfcheck.py 和 tests。更新原因和证据写到变更记录；禁止无根据地自我改写。

## 真实命令

项目预检查：
python <SKILL_DIR>/scripts/inspect_project.py --project-root <PROJECT_ROOT>

Skill 自检：
python <SKILL_DIR>/scripts/selfcheck.py --project-root <PROJECT_ROOT>

Benchmark 输入准备（需要私有 PDF 选择清单与 PyMuPDF）：
python <SKILL_DIR>/scripts/benchmark.py prepare --project-root <PROJECT_ROOT> --pages <PAGES.jsonl> --pdf-dir <PRIVATE_PDFS> --out <PRIVATE_INPUTS>

检查执行计划（不加载模型）：
python <SKILL_DIR>/scripts/benchmark.py plan --project-root <PROJECT_ROOT> --manifest <MANIFEST.jsonl> --providers rapidocr_ch_light paddleocr_v5_mobile --out <PRIVATE_PLAN>

真正本地运行（仅用户授权之后）：
python <SKILL_DIR>/scripts/benchmark.py execute --project-root <PROJECT_ROOT> --manifest <MANIFEST.jsonl> --providers rapidocr_ch_light paddleocr_v5_mobile --out <PRIVATE_RUN> --confirm-execute

对照报告：
python <SKILL_DIR>/scripts/benchmark.py compare --project-root <PROJECT_ROOT> --manifest <MANIFEST.jsonl> --predictions <BASE/predictions.jsonl> <NEW/predictions.jsonl> --out <PRIVATE_REPORT>

人工 GT 评分：
python <SKILL_DIR>/scripts/benchmark.py score --project-root <PROJECT_ROOT> --truth <REVIEWED_GT.jsonl> --predictions <BASE/predictions.jsonl> <NEW/predictions.jsonl> --out <PRIVATE_SCORE.json>

判定下一步：
python <SKILL_DIR>/scripts/evaluate_upgrade.py --manifest <MANIFEST.jsonl> --truth <REVIEWED_GT.jsonl> --baseline-predictions <BASE/predictions.jsonl> --candidate-predictions <NEW/predictions.jsonl> --baseline-provider <OLD> --candidate-provider <NEW> --out <PRIVATE_GATE.json>

## 必须保持的边界

Provider SUCCESS、HTTP 200、Audit PASS、输出相似度均不代表内容逐字正确；没有人工 GT 不得给出 OCR 准确率。生产配置无 Profile 时保留冻结路由；新增 Provider 必须完成 preflight / Normalizer 合同/模型推理和全链路验收。JudgeAI 固定提交不会随 PDFFast 升级自动改变。保护私有 PDF、标注、模型与预测文本，不得发布到 GitHub。

阅读 references/repo-contract.md 和 references/benchmark-upgrade-policy.md 获取项目合同及质量门禁。