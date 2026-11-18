# PDFFast Coding Agent 入场协议 v0.3.0

陌生 AI 不可仅靠旧摘要推断 V3。先核对当前源码和 Git 状态，再运行：

- `python <SKILL>/scripts/maintain.py doctor --project-root <REPO> --out <PRIVATE>/code-index`
- `python <SKILL>/scripts/change_impact.py --project-root <REPO> --topic <功能词> --out <PRIVATE>/impact.json`

读取 `references/project-guide.md`、当前 `docs/ARCHITECTURE.md`、`docs/PIPELINE.md`、`docs/INTEGRATION_ZH.md` 和相应源码，了解入口 `PDFFastParser.parse → ParseService → run_core_pipeline → Native/Evidence/Gate/Fallback/Provider/Canonical/Renderer/Audit → ParseResult`。

修改前写明目标接口、受影响文件、实际调用者、失败案例、验收条件；先加失败测试再改代码。运行定向测试和 `uv run pytest -q tests/unit tests/contracts tests/regression`；需要时做真实 PDF/HTTP/JudgeAI 回归。AST 索引仅辅助导航，不保证依赖图完整。

新 OCR 走 `real-ocr-upgrade.md`；不得因为发布新模型、Benchmark 相似度高或 Audit PASS 就声称内容更准。Skill 和项目维护于不同 Git 分支，变更后 `contract_sync.py check` 并复核，不能自动承认漂移。
