# OmniDocBench 60 页中文分层评测集

> 本文用于独立评测。请先确认本地数据的合法使用权限：官方 OmniDocBench 声明研究/非商业限制。不要上传官方图片、JSON 标注或预测全文到 GitHub。

## 分层方案

固定种子 42，所有图片为 simplified_chinese。类别互不重复：

| 标签 | 配额 | 筛选规则 |
| --- | ---: | --- |
| table_hard | 15 | 官方 subset=table_hard |
| equation_hard | 10 | 官方 subset=equation_hard |
| layout_hard | 10 | 官方 subset=layout_hard |
| research_report | 10 | 官方 subset=v1.5 + data_source=research_report |
| text_baseline | 15 | 官方 subset=v1.5、单栏、非 research_report、至少80个正文字符、无表格/图片/公式及未知区域类型 |

本方案利用官方页面属性与 layout_dets 做可复现分类；text_baseline 只是保守的普通正文候选定义，并不等于所有简单 PDF 页。research_report 并不保证没有表格/公式。测试文件是图片及封装光栅 PDF，不能测 pdfplumber 原生文本层分类能力。

## 执行

~~~bash
cd /Users/admin/Workspace/pdffast-provider-benchmark
git pull --ff-only
uv run --frozen --with pymupdf pytest -q tests/unit/test_provider_benchmark_stratified.py

uv run --frozen --with pymupdf python \
  -m tools.provider_benchmark.prepare_omnidocbench_stratified \
  --annotations /Users/admin/Workspace/PDFDataSet/OmniDocBench.json \
  --images-root /Users/admin/Workspace/PDFDataSet/images \
  --out outputs/provider_benchmark/omnidocbench_zh60_v1 \
  --seed 42 \
  --dpi 200
~~~

成功后 manifest.jsonl 应恰好包含 60 行，selection.json 保存配额、实际样本量、全部官方标注索引及数据集 SHA256 指纹。PDF 输入放在输出目录 assets/。官方图片仍从原下载目录引用，没有复制 60 份。

本脚本只选择样本并准备视觉输入：不会修改官方 GT，也不会伪造 CER、表格 TEDS、公式准确率。下一步需使用官方 OmniDocBench 评分器分别评测文字、表格和公式，再将得分与各页 benchmark_stratum 对齐。

## 安全预检

先使用 tools.provider_benchmark.run --dry-run 预检 Provider 配置和图片路径；不要立即将所有六模型跑满。由于 MiniCPM 是额外 Benchmark 插件，其名字必须在你之前生成的独立 providers.with_minicpm.json 中，不属于默认 configs/providers.json 生产名单。

注意：单张图片的 Provider 成本可能与之前 27 页不同，先验证分层样本和标注，再决定是否正式推理。
