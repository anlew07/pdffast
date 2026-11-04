# PDFFast V3 Provider 量化与配置切换指南（第一版）

## 目的与边界

这次只做 **生产 Profile 的候选链配置化 + 独立 Provider Benchmark**。不改 Native / Quality Gate / Capability Routing / Canonical / Audit 的判断语义，也不清理历史 Stage 名字。

- Benchmark 可以独立测试多个 Provider，不限于以后生产保留的 2–4 个。
- Production 按配置文件只启用候选中的 2–4 个（正式数量需以评测决定）。**新任务**读到新配置；不提供运行中热更新。
- 完整路由必须写全，不能只关掉配置中的某个 Provider 却让它继续出现在未覆盖的硬编码链中。
- 已有的六个内置 Provider、冻结基准文件、默认运行行为在**未指定 profile**时保持原样。
- 仓库内不提交业务 PDF、人工标注、预测文本、模型权重或公开数据集原始文件。

## 1. 生产 Profile 切换

示例：`configs/profiles/production.candidate.json`。这是 **未经 Benchmark 证明的示例组合**，不要当成最佳模型推荐。内容示意：

```json
{
  "schema_version": "1.0",
  "name": "production-candidate-NOT-benchmarked",
  "enabled_providers": ["rapidocr_ch_light", "mineru_local", "marker_local"],
  "chains": {
    "PAGE_DOCUMENT_OCR": ["rapidocr_ch_light", "mineru_local"],
    "PAGE_DOCUMENT_LAYOUT_PARSE": ["mineru_local", "marker_local"],
    "REGION_MULTIMODAL_PARSE": ["rapidocr_ch_light", "marker_local"],
    "INLINE_CONTEXT_PARSE": ["marker_local", "rapidocr_ch_light"]
  }
}
```

```bash
uv run python scripts/run_pipeline.py /private/input.pdf \
  --project-root . \
  --provider-profile configs/profiles/production.candidate.json \
  --output-root /private/ab_runs
```

`PDFFastParser(provider_profile=Path("configs/profiles/production.candidate.json"))` 也可直接使用。若生产配置本身另有 `provider_chain_overrides`，应只保留一种配置来源，避免冲突。

Profile 加载时检查四个 Capability Route 均有非空候选链、引用的 Provider 都在启用列表里、启用列表没有闲置模型。会复制配置并在本次解析中禁用其他 Provider；不会改写 `providers.json`。闭包检查和最终接受规则仍由原有执行器处理。

**注意：静态名单校验不等于每个模型真正满足 route 的能力合同。** 部署前还需独立 Preflight、结构通道检查及真实 PDF 回归。Profile 切换只对新任务生效。

## 2. 使用私有业务 PDF Pilot（推荐先做）

保留上一次私有 Pilot 包内的 `dataset/pilot_pages.jsonl`、`dataset/ground_truth.template.jsonl`；将原始 5 份 PDF 放在私有目录 `/private/pdfs`。制作 200 DPI 双格式视觉输入：

```bash
uv run python -m tools.provider_benchmark.prepare \
  --pages /private/pilot/dataset/pilot_pages.jsonl \
  --pdf-dir /private/pdfs \
  --out /private/provider_bench/inputs \
  --dpi 200
```

产生 `manifest.jsonl`、一张 PNG 和一个仅含光栅图片的单页 PDF。这里的 PDF 仅用于**视觉输入的 Provider 横向比较**，与原始矢量 PDF 的 Native-first 全链路测试是两件事。预览 JPG 不可当作正式 OCR 输入。

先检查任务、输入和模型目录，不加载模型：

```bash
uv run python -m tools.provider_benchmark.run \
  --manifest /private/provider_bench/inputs/manifest.jsonl \
  --project-root . \
  --providers rapidocr_ch_light paddleocr_v5_mobile mineru_local marker_local docling_local paddleocr_vl_16 \
  --allow-unapproved --out /private/provider_bench/run_001 --dry-run
```

确认模型环境已安装并就绪后，移除 `--dry-run` 运行。当前仓库配置中 MinerU/Marker `benchmark_enabled=false`，因此评测时要么使用已审批的独立评测配置，要么**明确**增加 `--allow-unapproved`。此参数只允许本次 Benchmark 测试，不会将其设为生产启用。

`run_001/predictions.jsonl` 按页记录状态、文本、推理耗时；`run_001/raw/<provider>/<page>/` 存放原始输出与 Canonical 标准化结果；`run_manifest.json` 保存数量及状态。预检失败、缺图、异常不会伪造成成功。

### 质量评分

仅使用 **人工完成并审核** 的 Ground Truth，不用 PDF 原生文本冒充标准答案：

```bash
uv run python -m tools.provider_benchmark.evaluate \
  --truth /private/pilot/dataset/ground_truth.template.jsonl \
  --predictions /private/provider_bench/run_001/predictions.jsonl \
  --out /private/provider_bench/score_001.json
```

首版量化字段：执行成功率、缺失/失败数、推理耗时 P50/P95、已审核文字的 CER（忽略空白）、关键字段**字面值出现召回**。最后一项只能表示文本中是否含该值，不等于字段识别正确，更不等于金额归属正确。

对表格（TEDS/Cell F1）、公式（CDM）和版面（mAP）的正式分数，必须另行使用与标注格式相匹配的评测器。**未提供真实 GT 时，不输出伪造的准确率。**

## 3. 使用已有公开测试集抽样

### OmniDocBench：文档完整解析（优先研究用）

- 官方代码：[opendatalab/OmniDocBench](https://github.com/opendatalab/OmniDocBench)
- 数据：[Hugging Face opendatalab/OmniDocBench](https://huggingface.co/datasets/opendatalab/OmniDocBench)
- 目前包含约 1651 页，标注文本、表格、公式、阅读顺序及布局。按**固定数据集版本**抽取中文/研究报告/含表格页，不必一次下载整个模型评测资源。
- 官方明确：**研究用途，不得商业使用**。如果本次评测属于公司商业研发，先取得合规授权；不同镜像站的许可证标签不能取代官方内容版权声明。

取得并核验当地的 `OmniDocBench.json` 与 `images/` 后：

```bash
uv run python -m tools.provider_benchmark.prepare_omnidocbench \
  --annotations /private/OmniDocBench/OmniDocBench.json \
  --images-root /private/OmniDocBench/images \
  --out /private/provider_bench/omnidocbench_30 \
  --limit 30 --seed 42 --language chinese
```

这个适配脚本只提取图像和写单页 PDF，保留官方标注文件原样；**暂未将 OmniDocBench 标注转成本项目的通用 GT**。高质量比较应使用官方评测器；可将本项目输出的每页 Markdown 与官方同名页映射后另行评估，不可混用结构分数。

### DocLayNet：页面布局

- 官方：[DS4SD/DocLayNet](https://github.com/DS4SD/DocLayNet)
- 约 80,863 页、11 类布局框，提供 COCO 标注；适合识别页面类别、标题/段落/表格/图片的布局位置。
- 它**不能直接代替中文整页文字 CER Ground Truth**。完整版数据很大（核心约 28 GiB），应先抽样或使用带过滤的数据集访问方法。官方许可证为 CDLA-Permissive-1.0，实际使用仍须核实协议与来源约束。
- 先拿本地已取得的 PNG 样本、COCO `test.json` 评估布局；**当前没有写 COCO mAP 评分适配器**。

### 中文专用 OCR

PaddleOCR 官方 [中文 OCR 数据集索引](https://www.paddleocr.ai/v3.6.0/datasets/datasets.html) 汇总 LSVT、RCTW 等，但这类数据偏街景文本，不是申报书整页版面。用于文字检测或识别单项能力验证，不能代替业务 PDF 样本；LSVT 测试集标注也未完全公开。

## 4. 最终选型原则

先按各 Capability Route 分组做 Provider 质量/耗时比较。保留一部分整份业务 PDF 作盲测，不要按同一 PDF 的不同页同时划入开发集和盲测集。

最后挑 2–4 个 Provider，要保证 OCR、复杂布局、局部图像及内联特殊内容的**真实表现**，而不是简单按平均 CER 选前四名。生产只安装入选 Provider 的运行环境；未入选模型留在 Benchmark 池，不随 JudgeAI 正式安装。

## 5. 当前验收状态

新增配置档与 Benchmark 脚本已经提交到 Draft PR。未在本机真实 Provider 模型环境跑通六模型推理、完整 pytest 或端到端 JudgeAI；**目前没有任何真实 Provider 排名**。公开数据集也未批量下载或提交到公开仓库。合并前应先用测试和本地模型环境验收。
