# Indra OCR — 统一 Runtime / JudgeAI 集成

Indra 不是新的 PDF 分类器：V3 先用 pdfplumber 做原生解析，Stage 8 决定哪些
页面/区域需要外部处理。**只有 Stage 9 的 Fallback 任务会调用 Indra OCR。**
Worker 长期存活，模型只在首次需要时加载，复用后续任务。

## 安装

在 pdffast-v3 根目录：

```bash
bash scripts/install_indra_runtime.sh
.venv/bin/python scripts/verify_indra_runtime.py --hashes --preflight
```

安装位于 `runtimes/indra/.venv`，模型位于
`runtimes/indra/models/indra-ocr`。包版本固定到 indra-ocr==1.1.2；
模型的不可变 revision SHA 和文件 SHA-256 写入
`runtimes/indra/install_manifest.json`，完整依赖快照写入
`runtimes/indra/requirements.lock`。
若用于 JudgeAI 部署，应设置 `INDRA_MODEL_REVISION=<批准的 SHA>`。
默认从 main 解析并记录实际 commit SHA；这**不意味着**不同时间安装会得到同一模型。
升级时保存原 manifest/lock 并进行 PDF 回归，旧环境可按记录回滚。

## 使用三模型（显式开启）

```bash
.venv/bin/python scripts/run_pipeline.py /path/to/case_002.pdf   --project-root . --provider-profile configs/profiles/production.indra-triple.json
```

- 整页 OCR：Indra → RapidOCR → MinerU。
- 结构解析整页：MinerU（不可纯 OCR 降级）。
- 区域识别：Indra → RapidOCR → MinerU。
- 图片文字上下文：Indra → MinerU → RapidOCR（回退到 RapidOCR 以覆盖 case_001 类型）。
- 没触发 Fallback 的原生文本不送到 Indra。
- Stage 9.8 接受条件保持不变；非空不代表准确，尤其关注 case_001 第 22 页标识。

此 Profile 为**候选版本**，不保证与本机上轮 5/5 benchmark 的路由参数完全一致；
正式交付前需使用原来的 5 份 PDF 回归，并人工核对中文关键字段。

## JudgeAI

JudgeAI 应通过 pdffast 的单一 Python API/适配层调用；
不要在 JudgeAI 中重复安装 Indra，也不要直接调用 Indra CLI。
JudgeAI 适配器必须**显式传递** V3 的 provider_profile 路径；
仅设置 `PDFFAST_PROVIDER_PROFILE` 环境变量并不会让当前 V3 自动读取它。
保留 `configs/profiles/production.speed.json` 回滚。
后续在 JudgeAI 统一固定 pdffast release/tag、runtime 依赖、模型 revision 和 Profile。

## 商用授权

Indra 代码 Apache-2.0；模型权重适用 modified OpenRAIL-M 的额外约束。
公司部署前必须单独核对模型许可：
https://huggingface.co/datalab-to/indra-ocr/blob/main/LICENSE

## 解析输出与完整日志

普通命令 `scripts/run_pipeline.py` 的终端输出只包含 Run ID、审计状态以及
`result/document.md`、`result/document.json`、`result/audit.json` 的路径。
**不再向终端打印完整 Markdown 和 Canonical JSON 内容。**

`scripts/verify_indra_runtime.py --smoke-pdf /path/to/case_002.pdf` 默认安静运行，
每次生成独立 `outputs/indra_triple_smoke/smoke_*/` 目录：
`smoke_console.log` 保存完整 stdout/stderr，子目录 `result/` 保存解析结果。
失败时终端只显示最后 25 行报错；原始日志不会截断。
历史已有运行结果可直接在 `outputs/indra_triple_smoke/` 下查找，
**不必因为终端滚动丢失而重新解析。**

