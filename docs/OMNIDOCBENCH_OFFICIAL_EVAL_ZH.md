# OmniDocBench 官方 GT 与 Provider 结果导出

当前 60 页中文分层输入已准备完成。此工具只做数据桥接，不执行模型推理或质量评分。

## 第一步：导出 60 页官方标准标注

在工作区执行：

~~~bash
cd /Users/admin/Workspace/pdffast-provider-benchmark
git pull --ff-only
uv run --frozen pytest -q tests/unit/test_provider_benchmark_official_export.py

uv run --frozen python -m tools.provider_benchmark.export_omnidocbench_official \
  --annotations /Users/admin/Workspace/PDFDataSet/OmniDocBench.json \
  --manifest outputs/provider_benchmark/omnidocbench_zh60_v1/manifest.jsonl \
  --out outputs/provider_benchmark/omnidocbench_zh60_official
~~~

生成 OmniDocBench.selected.json（60 页完整原始官方 GT）和 export_manifest.json（数据集校验结果）。

## 第二步：六模型解析后，导出官方评分输入

将以下示例预测文件路径替换成相同 60 页的真实 run 输出：

~~~bash
uv run --frozen python -m tools.provider_benchmark.export_omnidocbench_official \
  --annotations /Users/admin/Workspace/PDFDataSet/OmniDocBench.json \
  --manifest outputs/provider_benchmark/omnidocbench_zh60_v1/manifest.jsonl \
  --predictions path/to/run-a/predictions.jsonl path/to/run-b/predictions.jsonl \
  --exclude paddleocr_vl_16 \
  --out outputs/provider_benchmark/omnidocbench_zh60_official
~~~

会生成 predictions/模型名/原图文件名.md 和 configs/模型名.yaml。

## 正式评分

官方项目：https://github.com/opendatalab/OmniDocBench
官方 end2end 评分以原始 JSON GT 和按原图片名命名的 Markdown 为输入。评分工具要求 Python >=3.10,<3.12，必须独立于当前 PDFFast Python 3.12 环境部署，勿直接安装到项目 .venv。
评分时执行官方 pdf_validation.py --config <对应模型配置YAML>。本工具生成的 YAML 默认关闭 CDM，避免立即依赖整套 TeX Live/Ghostscript/ImageMagick 环境；文字使用 Edit_dist，表格使用 TEDS/Edit_dist，公式和阅读顺序使用 Edit_dist。

注意事项：

- 官方标注包含表格 HTML、公式 LaTeX、元素 order、ignore 和 relation；直接保存原对象，不拼接出不准确的通用全文。
- 失败/缺失预测写空 Markdown，计入覆盖情况，不可默默排除该页。
- 单图纯文本识别的 Provider 尚未验证表格和公式的结构输出；相关专项得分需标注能力范围或 N/A。
- 官方评分器执行前，只能声明 GT 已导出，不能声称 CER/TEDS 已获得。
- 当前 PDF 为单页图片封装，仅用于视觉 Provider 测试，不代表 pdfplumber 原生文本层路由测试。
- 官方数据及预测内容不要提交到 GitHub；遵守非商业研究使用限制。
