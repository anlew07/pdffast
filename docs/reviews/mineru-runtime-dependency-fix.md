# MinerU 运行依赖修复验收及真实推理验证

## 范围

仅处理 v3 的 MinerU runtime 依赖与提前检查。未修改中文日志任务涉及的 runtime/runner/executor 文件，未修改 HTTP、Canonical、Audit、心跳、路由或升级策略；未修改 v2/JudgeAI，未提交 Git，也未清理已有未提交内容。

本轮修改文件：

- `runtimes/mineru/pyproject.toml`
- `runtimes/mineru/uv.lock`
- `pdffast/providers/mineru.py`
- `tests/unit/test_mineru_dependencies.py`
- 本报告

runtime 配置文件原先已经有用户补充的 torch/torchvision 改动；本轮在其基础上启用 pipeline extra，并补充 six，保留原改动。

## 原因与真实初始化语义

`MinerUProvider` 使用 `IsolatedWorkerProvider` 与持久 JSONL Worker。Registry 校验模型 artifact；preflight 在独立 Python 子进程执行 dependency_probe_code；initialize 启动 Worker 并等待 READY；execute 发 parse 命令，之后才进入 do_parse。

旧 preflight 只执行 `from mineru.cli.common import do_parse, read_fn`。安装源码中 `cli/common.py` 的 pipeline 分支延迟导入 `mineru.backend.pipeline.pipeline_analyze`。旧 Worker 在发 READY 前只查询 MinerU 包元数据，不验证实际 pipeline imports，更不加载模型。所以 READY 表示协议进程就绪，不能证明推理环境完整。

历史 case_003 运行：`outputs/service/api_c20df2b1a1e345439edbf6070a671859`。其 selected predictions 中共有 7 个任务包含缺少 torchvision 的 MinerU attempt。Executor 复用已初始化 Provider，将每个 execute 错误记录为失败并按原 chain 升级，没有针对缺依赖的跨任务熔断。

## 修复

1. `mineru==3.4.5` 改为同版本 `mineru[pipeline]==3.4.5`。本机安装元数据明确将 PyYAML、ftfy、shapely、pyclipper、torch、torchvision、transformers、safetensors、onnxruntime 归入 pipeline extra。原 runtime 只声明基础 MinerU 和部分手工依赖，未包含整组后端运行依赖。
2. 增加 `six==1.17.0`：真实后端导入链到 `mineru/model/utils/pytorchocr/data/imaug/operators.py` 后直接导入 six；3.4.5 的 pipeline extra 未声明该依赖，实测缺失。
3. preflight 与 Worker READY 前显式导入 torch、torchvision、do_parse/read_fn，以及实际 `pipeline_analyze.doc_analyze_streaming`。仅导入代码，不实例化 MineruPipelineModel、不调用 do_parse/doc_analyze_streaming，不启动完整推理。Worker 检查的 stdout 重定向到 stderr，保持 JSONL 协议独占 stdout。

未改变 Executor 的重复尝试、Provider chain、任务结果或 escalation 算法。现在这些明确缺失依赖会在既有 preflight 阶段被拦截；绕过 preflight 直接 initialize 时也会 INIT_FAILED，而不是逐页 execute 后重复报同一依赖错误。preflight 失败仍按原 Executor 行为抛出，并不新增自动路由/熔断。

## 锁定与安装一致性

使用 uv lock 更新，再 uv sync --frozen 安装。输出仅新增以下包，未升级原三个固定版本。

| 包 | lock 与本机安装版本 |
|---|---|
| mineru | 3.4.5 |
| torch | 2.14.0 |
| torchvision | 0.29.0 |
| ftfy | 6.3.1 |
| pyclipper | 1.4.0 |
| shapely | 2.2.0 |
| wcwidth | 0.9.2 |
| six | 1.17.0 |

锁文件与实际环境均通过 tomllib/importlib.metadata 检查。依赖解析在沙箱 DNS 受限后通过获批的网络操作完成；安装范围仅 v3 `runtimes/mineru/.venv`。

## 真实单页验证

选取历史已失败任务，而非猜测输入：

- case_003 第 34 页。
- task_id：`s9_0034_page_fallback_32afc416c678`。
- 输入：上述历史运行 `09_1_fallback_units/inputs/page/p0034_page.png`。
- capability：`PAGE_DOCUMENT_LAYOUT_PARSE`。
- 配置：当前 `configs/providers.json` 的 mineru_local，经真实 Registry.create → preflight → initialize → execute → close。
- 后端 pipeline；parse_method=ocr；lang=ch；formula_enable=true；table_enable=true；原 timeout 和离线本机模型环境保持。
- raw_output_dir 指向独立验收目录，不覆盖原正式解析结果。

真实验证过程：

| 尝试 | 结果 |
|---|---|
| 顶层 torch/torchvision 检查后首次推理 | 约 9.06 秒失败：缺 shapely；证明顶层导入通过不足以验收 |
| 启用 pipeline extra 和实际后端检查后 | preflight 约 6.16 秒提前发现缺 six；未进入页面推理 |
| 补锁并安装 six 后 | SUCCESS，真实单页推理成功 |

最终耗时：preflight 4.775 秒；Worker 初始化 3.269 秒；execute 8.670 秒（Worker 报告 8.664 秒）；close 0.842 秒；总计 17.556 秒。

产出 3831 字符 Markdown，以及 MinerU content_list_v2/content_list/middle JSON。随后用现有 normalize_runtime_result 验证：status=SUCCESS，5 个 reading_blocks、3 个 tables；formulas=UNSUPPORTED、0 个（不据此宣称公式恢复）。实际日志显示模型初始化只发生在 execute 期间，而非上述 import-only preflight。

输出目录：`outputs/mineru_dependency_fix_review/`。保留 first-attempt/second-attempt 日志与结果、最终 verification.log，以及任务子目录的 verification.json、document.md、raw/mineru_output、normalized_prediction.json、normalized_summary.json。

## 回归测试

新增 6 个参数化检查：preflight/Worker 两个边界分别验证缺 torch、缺 torchvision、后端传递导入缺失都不能进入 READY/推理。测试先失败再修复；fake import 的推理函数调用会使测试立即失败。

本轮实际结果：

- 依赖检查 + Provider lifecycle + HTTP/runtime logging integration：34 passed，0 failed。
- 完整 unit/contracts/regression：340 passed，20 skipped，0 failed。
- reference-bound 完整测试：360 passed，0 skipped，0 failed。
- git diff --check：PASS。

v3 当前主 `.venv` 没有 pytest。回归使用本机既有 v2 Python 测试依赖，通过 PYTHONPATH 明确指向 v3，关闭 bytecode 与 pytest cache；未修改 v2 文件。真实 MinerU 使用 v3 主 Python 驱动、配置指定的 v3 MinerU runtime Python 推理。HTTP v1 响应、Canonical/Audit 与心跳并发/清理测试包含在本轮回归中；未重新执行完整 HTTP case_003。

## 是否需要重跑 case_003

依赖修复和单页真实推理验收已完成，无需为确认此故障修复直接重跑 66 页。若要取得修复后完整输出并测量真实端到端耗时，则需要另行重跑 case_003；旧输出不会因安装依赖而自动改变。本轮未执行该重跑，也不根据单页结果承诺全文件耗时或结果完全一致。
