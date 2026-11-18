# PDFFast V3 项目合同（创建时快照）

核对源：anlew07/pdffast main，commit 164fc49c1a4bc305864639a4a5fc36be2f098489。每次启动仍需读取实时源码，发现不同即更新此文档。

- V3 使用 Python 对象传递 Native、Evidence、Quality、Fallback、Canonical 结果；JSON 仅供诊断/回放，不能回退为旧版 Stage 文件总线。
- 默认六 Provider：rapidocr_ch_light、paddleocr_v5_mobile、paddleocr_vl_16、mineru_local、marker_local、docling_local；MiniCPM OCR 是可选候选，不进入默认生产配置。
- ProviderRegistry 经 configs/providers.json 显式 plugins 注册，不自动扫描第三方代码；Adapter 须有 preflight、initialize、execute、close；Normalizer 输出 CanonicalPrediction。
- 四个能力路由：PAGE_DOCUMENT_OCR、PAGE_DOCUMENT_LAYOUT_PARSE、REGION_MULTIMODAL_PARSE、INLINE_CONTEXT_PARSE。
- Profile 在 configs/profiles/*.json，完整覆盖四条链；生产冻结行为不应被意外改变。benchmark_enabled 与 runtime_enabled 是不同的开关。
- 本仓库已有 tools.provider_benchmark.prepare/run/evaluate/report。run 的 --dry-run 是预检；输出 predictions.jsonl 和 run_manifest.json；report 是逐页对照，不是准确率认证；evaluate 只在 reviewed/approved GT 下算 CER。
- 真实模型环境要求另行验证。完整项目回归：uv run pytest -q tests/unit tests/contracts tests/regression；SKIP 不等于 PASS。
- JudgeAI 固定 PDFFast 的 Git 提交，变更 PDFFast 不会自动更新 JudgeAI。

项目内优先阅读 README.md、docs/PROVIDER_PLUGINS_ZH.md、docs/PROVIDER_BENCHMARK_ZH.md、docs/PROVIDER_RUNTIME_ENVIRONMENTS.md、docs/MINICPM_OCR_BENCHMARK_ZH.md。