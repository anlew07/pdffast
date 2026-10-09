# PDFFast v3 Runtime Logging & Heartbeat

## 范围与设计

本轮只增加运行日志和心跳；保持 R3-B 对象传递、R4-B ArtifactPaths、HTTP v1、ParseResult、Canonical、Markdown、Audit 和 Provider 策略。没有修改 v2 或 JudgeAI。

每次 parse 拥有独立轻量观测状态；标准 logging 发出 JSON 日志消息，默认每 30 秒心跳。使用 monotonic clock 计算持续时间；只有真实阶段/任务事件更新最后进展时间。用户已确认此方案。实施采用先失败再通过的测试，并按 requesting-code-review 技能完成独立检查。

## 1. 原有日志机制

`PDFFastParser` 转交 `ParseService`，后者组织依赖并调用 `run_core_pipeline`。HTTP `/parse` 同步执行公开 Parser，Uvicorn access log 在返回响应后出现。

原有 `capture_runtime_output` 将解析输出追加到现有 `diagnostics/logs/pipeline.log`，通过替换全局 stdout/stderr 与 root handlers 捕获日志。这能保留调试输出，但不能提供语义进展，也不适合多个请求同时捕获。

现有 runner 的异常包装及 traceback 输出仍保留。Provider Executor 原来允许任务错误进入既有 escalation/terminal 路径，此行为保持。

## 2. 新增日志位置

| 位置 | 事件/职责 |
|---|---|
| `pdffast/runtime.py` | run 状态、实时 logging、心跳、异常上下文、并发日志捕获 |
| `pdffast/application/parse_service.py` | parse_started、parse_finished/failed；覆盖依赖配置准备 |
| `pdffast/pipeline/runner.py` | Native 开始/结束及内部语义进展；Evidence、Quality、Fallback、Capability、Provider、Canonical、Renderer、Audit |
| `pdffast/fallback/executor.py` | Provider 初始化、任务开始/完成/失败、terminal 完成、执行结束 |

主要事件：`parse_started`、`native_analysis_started/finished`、`quality_completed`、`fallback_planning_completed`、`provider_execution_started/finished`、`provider_task_started/finished/failed`、`canonical_completed`、`renderer_completed`、`audit_completed`、`parse_finished/failed`。

额外细化 Native 为 `native_observation`、`section_discovery`、`page_structure`、`table_recovery`、`text_flow`，使长任务的 current_phase 有实际意义。不新增 Stage 编号。

所有事件使用 logger `pdffast.runtime.events`，消息为一行 JSON，并附同名 LogRecord 属性。独立实时 handler 写入 stderr 并 flush，避免被普通 debug capture 隐藏；宿主可给该 logger 增加 collector。开启原有 capture_output 时，事件也追加到原有 pipeline.log。没有增加 Artifact 路径或响应字段。

## 3. 心跳实现

每次运行拥有一个可停止线程、一个 Event、一把短持有的状态锁。线程通过 `stop.wait(30)` 等待，读取状态快照后输出 `parse_heartbeat`。解析计算不在心跳线程中，也不等待心跳到点。内部测试可指定短周期；公开 Parser/HTTP 参数保持原样。

通用字段：

- `timestamp`：UTC 时间。
- `run_id`、`current_phase`。
- `elapsed_seconds`：本次 parse 已运行时间。
- `last_progress_elapsed_seconds`：距最后真实进展的时间。

Provider 字段仅在已知时出现：`provider`、`task_id`、`task_elapsed_seconds`、`completed_tasks`、`total_tasks`。总数来自已生成的 execution plan；完成数来自 executor 的 done 状态，包含终结 unresolved，不将失败重试计为完成。不推算 ETA、百分比或未发现的任务。

心跳示意（数值仅为示例）：

```json
{"event":"parse_heartbeat","run_id":"api_example","current_phase":"provider_execution","elapsed_seconds":90.0,"last_progress_elapsed_seconds":32.0,"provider":"mineru_local","task_id":"task_example","task_elapsed_seconds":32.0,"completed_tasks":2,"total_tasks":5}
```

## 4. 真实进展与异常

心跳不更新 `_last_progress`。阶段进入/完成、Provider 初始化、任务完成以及 terminal 状态推进才更新它。间隔持续增长表示当前计算长时间没有记录到新的进展，不能单独证明死锁或失败。

异常事件包含 `exception_type`、`exception_message`、run/phase 及适用的 provider/task。LogRecord 携带 exc_info，现有日志机制可格式化 traceback；pipeline.log 保留 traceback。任务错误仍按原 Executor 行为尝试 escalation；`provider_task_failed` 不等于整个 parse 失败。`parse_finished` 只表示函数正常完成，不替代质量判定或 Audit 结论。

解析异常继续传播；runner 原有 ParseExecutionError 包装保持。观测日志 sink 的写入/关闭错误采用 best effort，不替换原解析异常，也不改变 Provider 结果。独立检查发现的异常覆盖与 observer 清理问题已加回归并修正。

## 5. 并发隔离与资源清理

ContextVar 保存当前观察对象；心跳线程显式持有所属 run 状态。HTTP 每次请求已有独立 UUID run_id。ParseService 与 runner 的同次嵌套只创建一个心跳和一组 parse 生命周期事件。

普通 Python stdout/stderr 使用共享路由器按当前 context 分流，root logging 保留宿主 handler 并添加捕获 filter；不同请求的日志不混写，未捕获宿主线程仍写宿主日志。最后一个 capture 退出后恢复原 stream/filter/handler 状态。

成功、Exception、KeyboardInterrupt、SystemExit、asyncio.CancelledError 沿上下文退出时，先 set Event 并 join 心跳，再发 terminal 日志、关闭文件、finally reset ContextVar。测试断言结束后无新心跳、无遗留线程；重复启动/停止和 sink 关闭失败同样覆盖。状态不持有 PDF/图片/任务 payload 等大型对象。

这里处理的是解析栈实际退出时的清理。同步 HTTP 客户端断开不会因此新增自动取消解析功能；进程被强制 SIGKILL 时也无法执行 Python finally。第三方自行创建的线程或直接 OS fd 输出不保证获得当前 ContextVar；本轮保证 PDFFast 语义事件的 run 隔离。没有引入监控队列、状态 endpoint、SSE 或 WebSocket。

## 6. 测试

新增：

- `tests/unit/test_runtime_observation.py`：实时/文件输出、定时心跳与真实进展分离、四种异常退出、并发捕获、重复清理、嵌套、日志 sink 失败、宿主日志、文件关闭失败。
- `tests/unit/test_runtime_logging_integration.py`：正式 runner 事件顺序、异常阶段、配置失败、真实 Executor 的 fake Provider escalation/terminal/count、并发 HTTP v1 响应合同。测试不启动重型 Provider。

本轮实际执行（不是历史冻结数字）：

| 验证 | 结果 |
|---|---|
| 改动前完整 unit/contracts/regression | 316 passed / 20 skipped / 0 failed |
| 新日志/心跳专项 | 17 passed / 1 skipped / 0 failed |
| 改动后完整 unit/contracts/regression | 333 passed / 21 skipped / 0 failed |
| HTTP v1 并发/合同单独验证 | 1 passed / 0 failed |
| reference-bound 完整测试 | 353 passed / 1 skipped / 0 failed |
| git diff --check | PASS |

v3 默认环境没有 FastAPI/service extra，专项与完整测试多出的 1 skip 为 HTTP 测试。HTTP 单独验证使用本机既有 `/Users/admin/Workspace/pdffast-v2/.venv/bin/python`，通过 PYTHONPATH 指向 v3，并关闭 bytecode/cache 写入；执行的是 v3 源码，未修改 v2。没有为了测试安装或启动真实 OCR 模型。

uv 使用 `UV_CACHE_DIR=/private/tmp/pdffast-v3-uv-cache uv run --no-sync`，避开受限的默认缓存。reference-bound 使用 `/Users/admin/Workspace/pdffast` 和其 case_002.pdf。

## 7. JudgeAI 后续读取方式

目前可由服务运维日志采集器订阅 stderr，按 run_id 聚合事件；启用 capture 时也可查看各 run 的 `diagnostics/logs/pipeline.log`。`parse_heartbeat` 用于确认解析仍在执行，阶段/任务事件用于判断真实进展，错误事件用于定位异常。

POST /parse 仍同步返回 schema_version=1.0、run_id、markdown、canonical、audit；调用方当前在响应后获得 run_id。直接让 JudgeAI 在请求期间查询状态需要未来另行设计关联和日志读取方案，本轮没有实现集成或新的状态接口。

## 结论

日志和心跳覆盖正式对象驱动运行链；Provider 路由/选择、产物内容和 HTTP 响应合同保持。到此停止，不进入 JudgeAI 集成、v2 或后续架构重构。
