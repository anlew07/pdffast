# PDFFast HTTP 日志分级与第三方降噪

## 真实来源与修改边界

`runtime.py:ParseObservation._emit` 生成英文事件及 JSON 消息，分别交给实时 logger 和本次运行的 FileHandler。实时 `_LiveEventHandler` 使用中文 Formatter，绕过已有按解析上下文的普通输出捕获，立即写终端 stderr。此次只在这个控制台 Handler 上设置 Filter；未降低事件 logger 级别，未过滤结构化 FileHandler。

`providers/workers.py:JsonLineWorker.start` 使用 stdin/stdout PIPE，stderr=None。stdout 为 JSONL 协议；stderr 继承服务终端。MinerU Worker 原有 redirect_stdout(sys.stderr) 保护模型 print 不污染 stdout，此次没有新增全局重定向。

锁定 MinerU 3.4.5 的 `backend/pipeline/pipeline_analyze.py` 从 Loguru 获取 logger，从 tqdm 获取进度条：INFO 模型初始化/推理统计、DEBUG 批处理提示、Processing pages 进度条。`cli/common.py` 还使用 WARNING。安装的 tqdm 支持导入时读取 TQDM_DISABLE。降噪限定在新建的 MinerU Worker 进程，不修改第三方源码，不影响其他请求。

## 配置与生效时间

`PDFFAST_LOG_MODE=quiet|normal|debug`，默认 normal，大小写/前后空白归一化，无效值明确 ValueError。

- 事件 Handler 在 runtime 模块加载、服务进程启动时固定模式。
- 新入口 `python -m pdffast.service` 构建 Uvicorn 配置时读取模式；quiet access_log=False，错误日志不关闭。
- MinerU 子进程启动时读取继承环境，在导入 MinerU/tqdm 前设置局部显示配置。
- 不支持正在运行的服务热更新环境变量。新模式需对未来新服务启动配置；本轮没有重启或停止 8010。
- 直接运行其他 Uvicorn CLI 入口不会自动采用此入口的 access_log 设置，需用入口或显式 CLI 配置。

## 分级规则

| 模式 | 控制台 PDFFast 事件 | MinerU | Uvicorn access |
|---|---|---|---|
| quiet | 开始/结束/失败、30秒心跳、重要异常及捕获异常 | WARNING+，进度条关闭 | 关闭 |
| normal | 以上+Native/Evidence/Quality完成、增强规划/执行摘要、Canonical/Renderer/Audit完成、补充证据诊断 | WARNING+，进度条关闭 | 保留 |
| debug | 原有逐阶段、初始化、任务开始/结束、尝试、诊断详情 | 保持原 Loguru/tqdm 配置 | 保留 |

所有模式保留明确 FAILED、SUCCESS_WITH_WARNINGS、exception/traceback、清理失败。补充捕获 FAILED/PARTIAL/UNAVAILABLE/MISSING/EXPORT_FAILED/NOT_CALLED 在 quiet 也显示，不能解释成没有脚注。定期任务完成摘要复用原有心跳完成数，不增加计时器、线程或虚构百分比。

## 标识和事件兼容

ParseObservation 分配 `<PID>:r<进程序号>`。同一进程的序号不复用，并发进程 PID 不同，无映射缓存或无界历史状态。短标识适用于当前进程生命周期；跨重启历史关联仍使用完整 run_id。

normal/quiet 开始、结束及异常同时显示短标识与完整 run_id，异常显示完整 task_id。普通中间事件移除重复阶段、完整任务编号和原始状态；Provider ID 仍保留。debug 保持原格式。只有日志 Record 的展示属性增加 console_run_id，JSON消息字段、英文event、原始计时和 Provider Attempt/Production Manifest 不变。

前（debug）：

```text
[PDFFast][任务执行] 开始处理 | 运行编号：api_noise_probe_unique | 阶段：增强执行 | Provider：MinerU（provider_id=mineru_local） | 任务编号：task_0 | 已完成任务：0/54 | 累计运行：0.0 秒
```

后（normal）：逐任务成功尝试隐藏，阶段与心跳继续实时输出：

```text
[PDFFast][解析开始] 开始处理 PDF | 运行编号：api_noise_probe_unique（运行：89604:r1） | 阶段：解析准备 | 累计运行：0.0 秒
[PDFFast][原生解析] 已完成 | 运行：89604:r1 | 累计运行：0.0 秒
[PDFFast][运行心跳] 正在执行 MinerU | 运行：89604:r1 | Provider：MinerU（provider_id=mineru_local） | 已完成任务：54/54 | 累计运行：0.0 秒 | 当前任务耗时：0.0 秒 | 距上次真实进展：0.0 秒
```

示例来自快速故障注入探针，0.0 秒是真实采样四舍五入，不是完整PDF耗时；探针手动发心跳事件，不冒充等待30秒。原计时线程语义由既有测试验证。

## MinerU 局部配置

新增 `providers/worker_logging.py:MINERU_LOGGING_CODE`，拼在 MinerU 原 Worker 代码之前。normal/quiet 设置 TQDM_DISABLE=1，再以 Loguru 官方 remove/add API 将 Worker 的 sink 设置为 stderr/WARNING。不丢弃整个 stderr，Python traceback、模型 WARNING/ERROR 原样保留。debug 不替换 sink，不覆盖操作员已有 tqdm 配置。

Loguru 在轻量测试解释器不存在时，仅发出降噪不可用 WARNING，让原依赖初始化按既有路径报告错误，不新增主环境对 Loguru 的依赖；真实 MinerU 环境中库已存在。降噪不保证屏蔽第三方裸 print、另行安装的 sink 或显式 disable=False 的进度条；不为追求静默做通道过滤或修改模型。

## 隔离行数验证

三个独立子进程，各生成同样54次任务开始/完成、阶段、心跳和一次 TimeoutError 故障。结果存于 `outputs/runtime_log_noise_validation/`：

| 模式 | runtime控制台行数（含traceback） | 完整结构化事件 | 真实Loguru/tqdm探针stderr行数 |
|---|---:|---:|---:|
| debug | 126 | 123 | 68 |
| normal | 15 | 123 | 5 |
| quiet | 7 | 123 | 5 |

三种模式结构化事件序列完全相同。既有 FileHandler 日志包含123条JSON事件及3行异常traceback，共126行，不能把traceback行计作事件。

相同探针 normal 行数减少约88.1%，quiet约94.4%；不是对完整 case_003 或实际批量导入的承诺。模型探针使用当前 MinerU .venv 的真实 Loguru/tqdm，30次DEBUG/INFO、进度条、WARNING/ERROR和ValueError traceback；三种模式 stdout 都是合法 READY JSONL，traceback保留。未重新调用完整模型推理；不宣称真实所有模型日志均已验收。

## 修改文件

- pdffast/runtime.py：实时 Handler 模式、运行展示标识；原线程/计时/事件/文件输出不变。
- pdffast/runtime_format.py：集中模式校验、控制台过滤、紧凑中文展示。
- pdffast/providers/worker_logging.py：Worker 局部库配置。
- pdffast/providers/mineru.py：拼入配置，无执行参数/捕获协议改变。
- pdffast/service/__main__.py：quiet访问日志配置。
- tests/unit/test_runtime_log_modes.py：三种模式、JSONL、日志库、并发、异常、配置、捕获问题测试。
- tests/unit/test_runtime_chinese_format.py、test_runtime_observation.py：原逐任务详细展示测试显式debug，保留原断言和独立Collector。
- 本报告。

## 生命周期与剩余风险

心跳仍默认30秒，仅 progress 更新 last_progress，Filter不修改任何状态；stop/join和Worker terminate/wait/kill、取消路径未改。未改 Pipeline、Provider路由、超时、Acceptance、Canonical、Markdown、Audit、Supplemental Evidence合同、HTTP v1。

第三方 inherited stderr 未标注 run_id，不错误归给另一个请求；任务异常仍由正式事件提供完整关联。剩余裸print/其他Provider噪声留待真实观察，不扩展为生命周期重构。当前8010实例保持原有启动时配置，需要未来经用户确认更新模式。

没有运行完整case_003、没有修改JudgeAI/v2、没有清理或提交工作区。

## 最终实际测试结果

| 执行范围 | 结果 | 耗时 |
|---|---|---|
| 最终日志模式专项 | 13 passed | 0.62秒 |
| 日志/Worker生命周期/服务退出/异常清理联合专项 | 124 passed，0 failed | 10.72秒 |
| 完整 unit/contracts/regression | 453 passed，20 skipped，0 failed | 35.64秒 |
| Reference-bound 全套 | 473 passed，0 failed | 148.59秒 |

联合专项包含10个真实 Uvicorn 信号场景，使用各自临时目录和随机端口；没有借用/重启8010。完整回归的20个skipped全部为未配置参考资源的既有用例，reference-bound全部执行。

命令：

```bash
.venv/bin/python -m pytest -q tests/unit/test_runtime_log_modes.py
.venv/bin/python -m pytest -q tests/unit/test_runtime_log_modes.py tests/unit/test_runtime_chinese_format.py tests/unit/test_runtime_observation.py tests/unit/test_runtime_logging_integration.py tests/unit/test_provider_lifecycle.py tests/unit/test_service_shutdown.py tests/unit/test_shutdown_cleanup.py
.venv/bin/python -m pytest -q tests/unit tests/contracts tests/regression
PDFFAST_REFERENCE_ROOT=/Users/admin/Workspace/pdffast \
PDFFAST_SAMPLE_PDF=/Users/admin/Workspace/pdffast/benchmark/samples/real/case_002.pdf \
.venv/bin/python -m pytest -q tests/unit tests/contracts tests/regression
git diff --check
```

git diff --check及修改Python文件语法检查通过。初次回归发现轻量解释器无Loguru导致原依赖错误被提前遮蔽，已改为降噪不可用WARNING且继续既有初始化；另发现原Worker exec测试会在本进程留下TQDM_DISABLE，独立库探针显式清除该变量来建立可重复基线。没有删除测试或放宽原依赖校验、内容、HTTP、Worker清理断言。原详细控制台测试改为显式debug，并保留原断言；默认normal行为由新增测试覆盖。

当前未提交的既有 :memory:.ses、experiments/、tools/acceptance/ 和前轮JudgeAI验收报告原样保留。本轮只增加上列9个日志相关生产/测试/报告文件的变更。未提交、push或清理。
