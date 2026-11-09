# OmniDocBench 标准答案与官方评分器对接

## 用途和注意

本工具只在本地筛出已固定的 60 页原始标注，并将 Provider 的完整预测文本按官方图片名导出成 Markdown。**不改写标注、不用某个模型预测充当 GT、不自行声称准确率。** 完整数据集的官方标注、图片及模型输出都不要上传仓库。OmniDocBench 仅限研究/非商业用途，商业研发前须核实授权。

官方 end2end 评分器读取含 layout_dets/page_info/extra 的原始标注数组，预测格式为按原图文件名命名的 .md，并计算文本 Edit_dist、表格 TEDS、公式 CDM、阅读顺序 Edit_dist 等。推荐后续将官方评价作为正式得分来源，不用现有 report.py 的“文本重合度”代替。

## 1. 导出与 60 页 Manifest 严格一致的官方标注

~~~bash
cd /Users/admin/Workspace/pdffast-provider-benchmark
git pull --ff-only
uv run --frozen pytest -q tests/unit/test_provider_benchmark_omnidocbench_official.py

uv run --frozen python -m tools.provider_benchmark.omnidocbench_official prepare-gt \
  --manifest outputs/provider_benchmark/omnidocbench_zh60_v1/manifest.jsonl \
  --annotations /Users/admin/Workspace/PDFDataSet/OmniDocBench.json \
  --out outputs/provider_benchmark/omnidocbench_zh60_v1/official_eval
~~~

输出 official_gt_subset.json（原样保留所有标注字段）、mapping.jsonl（page_id 与官方图片文件名对应关系）、export_summary.json。工具验证原始完整标注的 SHA256 与 selection.json 一致，并拒绝错配或重复图片。

## 2. 六模型推理完成后，导出官方 Markdown 预测

（示例：根据新 60 页真实运行输出，传入一份或多份 predictions.jsonl。**不能使用此前 27 页不同数据集的结果。**）

~~~bash
uv run --frozen python -m tools.provider_benchmark.omnidocbench_official export-predictions \
  --mapping outputs/provider_benchmark/omnidocbench_zh60_v1/official_eval/mapping.jsonl \
  --predictions outputs/provider_benchmark/omnidocbench_zh60_run/predictions.jsonl \
  --out outputs/provider_benchmark/omnidocbench_zh60_v1/official_predictions
~~~

生成 official_predictions/<Provider>/<原图片stem>.md，并输出每个 Provider 成功、失败、缺失页面数。失败页面不生成 Markdown，官方评测器将其视为空预测。重复导出请使用新的输出目录，防止旧预测污染评测。

## 3. 正式质量评分

使用官方 OmniDocBench 主分支对应 v1.6 的 end2end 评价程序，GT 文件指定上一步 official_gt_subset.json，每次 prediction.data_path 指向一个 Provider 文件夹。官方环境的 CDM 依赖较重且通常需要独立 Python 3.10、TeX Live、Ghostscript、ImageMagick。Mac 无 Docker 环境可以先验证文字 Edit_dist/TEDS 的官方评价，再单独接公式 CDM。准确运行命令需要固定官方仓库版本与本地评分环境后确认。

注意：目前仅完成 60 页样本选择与原始 GT 导出工具；未运行真实六模型 60 页推理或官方评价，因此没有质量排名。
