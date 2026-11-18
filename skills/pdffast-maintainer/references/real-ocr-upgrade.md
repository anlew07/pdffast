# 新 OCR 实验、比较、替换及回滚 v0.3.0

## 1. 寻找候选
运行 `technology_radar.py --online`，进一步审查官方 GitHub Releases、README、模型卡、许可、PyPI、官方 Benchmark。官方入口见 `technology-sources.json`，至少覆盖 PaddleOCR、RapidOCR、MinerU、Docling、Marker、olmOCR、Tesseract。记录源 URL、commit/tag、商用限制、推理硬件、模型大小和目标路线。不能单靠“更新”判断“更好”。

## 2. 确定当前基线与能力路线
读 `configs/providers.json`、`providers/registry.py`、`fallback/policy.py`、`configs/profiles`。分别选择 PAGE_DOCUMENT_OCR、PAGE_DOCUMENT_LAYOUT_PARSE、REGION_MULTIMODAL_PARSE、INLINE_CONTEXT_PARSE；不能用单模型总分替代每条路由质量。

## 3. 隔离接入
```bash
git -C <REPO> status --short
git -C <REPO> worktree add -b experiment/<CANDIDATE> <PRIVATE_WORKTREE> main
uv venv <PRIVATE>/.venv --python 3.12
python <SKILL>/scripts/candidate_scaffold.py --candidate <candidate_id> --route PAGE_DOCUMENT_OCR --out <PRIVATE>/scaffold
python <SKILL>/scripts/experiment_config.py --project-root <PRIVATE_WORKTREE> --fragment <PRIVATE>/scaffold/registry-fragment.json --out <PRIVATE>/providers.lab.json
```
骨架 Adapter/Normalizer 故意 NOT_IMPLEMENTED；必须基于官方 SDK 和 `pdffast/providers/base.py`、`runtime_normalization.py`、`minicpm_normalizer.py` 完成。经许可再安装锁定依赖与模型，Preflight → 单页 Smoke → RawResult → CanonicalPrediction → 失败/超时/关闭验证。仅使用私有 Registry，不动默认生产链。

## 4. 同输入 A/B
先用 `tools.provider_benchmark.prepare` 生成固定 DPI PNG 与 raster-only 单页 PDF。再按顺序执行：
```bash
python <SKILL>/scripts/experiment.py init --project-root <PRIVATE_WORKTREE> --lab <PRIVATE>/exp01 --manifest <PRIVATE>/inputs/manifest.jsonl --provider-config <PRIVATE>/providers.lab.json --baseline <OLD> --candidate <NEW> --truth <PRIVATE>/approved_gt.jsonl --python <PRIVATE>/.venv/bin/python --allow-unapproved
python <SKILL>/scripts/experiment.py plan --lab <PRIVATE>/exp01
python <SKILL>/scripts/experiment.py run --lab <PRIVATE>/exp01 --confirm-inference
python <SKILL>/scripts/experiment.py evaluate --lab <PRIVATE>/exp01
python <SKILL>/scripts/experiment.py status --lab <PRIVATE>/exp01
```
锁定真实图片/PDF 输入哈希、Manifest、Registry、GT 和相关源码；预测被篡改、缺页、混用输入、失败清理，都不能当 PASS。缺 GT 不得报告准确率；表格、公式、阅读顺序单独评估。

## 5. 替换和回滚
`evaluate_upgrade.py` 的 READY_FOR_END_TO_END **不是生产准入**。经真实文字 GT 比对后用 `propose_profile.py` 结合 Gate 身份生成待审四路由 Profile，再跑原始完整 PDF、Canonical/Markdown/Audit、失败回退、HTTP 和 JudgeAI 锁定提交的兼容性回归。维护者批准后才提交并启用新 Provider。回滚恢复原生产 Profile、Registry 和锁定代码版本，不删除实验原始证据。私有 PDF/GT/OCR 结果禁止提交 GitHub。
