# Runtime Logging 中文可读化

## 实施计划

仅新增集中展示 Formatter，并给现有实时 Handler 接入。结构化 JSON 文件与 LogRecord 保持原样；不变更运行状态、心跳、事件发射、Provider 或 HTTP。

1. 先编写并运行中文映射、未知回退、状态区分、traceback、结构化兼容、实时单次输出测试，确认现有实现缺少中文展示。
2. 新增 `pdffast/runtime_format.py`：事件/阶段/Provider 名称集中映射；无状态 Formatter，按已有字段展示，不臆造阶段耗时或 Audit 结果。
3. `pdffast/runtime.py` 仅接入 Formatter；更新旧控制台 JSON 断言，保留结构化原值检查。
4. 运行运行日志/Provider/HTTP 测试及完整回归，记录实测结果和展示样例。

不提交、不清理、不启动完整 case_003。测试环境沿用已验证的本地 Python 测试依赖，代码指向 v3。

## 原有日志实现与修改范围

`ParseService.parse` 创建独立观察上下文，runner 同次嵌套复用。`ParseObservation` 用 ContextVar 关联 run，以 monotonic clock 记录真实进展；心跳线程每 30 秒读取其所属状态。runner 与 Executor 在真实阶段/任务边界发英文事件。

`_emit` 生成 JSON message，并将 event/run_id/phase/provider/task/时间等数据附在 LogRecord 上。此前实时 `_LiveEventHandler` 直接写 record.getMessage() 到 stderr，解析文件 FileHandler 同时持久化 JSON。普通 stdout/stderr 的 ContextVar 捕获负责每次解析的调试日志。

本轮只修改/新增：

- `pdffast/runtime_format.py`：集中事件、阶段、Provider 映射与无状态 ChineseRuntimeFormatter。
- `pdffast/runtime.py`：导入 Formatter，给现有实时 Handler 设置 Formatter，使用 self.format(record) 输出。
- `tests/unit/test_runtime_chinese_format.py`：新增展示与结构化兼容、并发测试。
- `tests/unit/test_runtime_observation.py`：旧控制台英文事件断言更新为中文展示；原始事件和文件 JSON 断言保留。
- 本报告。

未修改 ParseService、runner、Executor、Provider、HTTP、ArtifactPaths、Canonical、Markdown 或 Audit；保留工作区原有未提交改动，不提交、不清理，不运行完整 case_003。

## 中文事件映射

| 原始 event | 中文类别 | 默认说明 |
|---|---|---|
| `parse_started` | 解析开始 | 开始处理 PDF |
| `native_analysis_started` | 原生解析 | 开始分析 |
| `native_observation_completed` | 原生观察 | 已完成，开始章节发现 |
| `section_discovery_completed` | 章节发现 | 已完成，开始页面结构分析 |
| `page_structure_completed` | 页面结构 | 已完成，开始表格恢复 |
| `table_recovery_completed` | 表格恢复 | 已完成，开始文本流整理 |
| `native_analysis_finished` | 原生解析 | 已完成 |
| `evidence_started` | 证据检查 | 开始执行 |
| `evidence_completed` | 证据检查 | 已完成 |
| `quality_completed` | 质量检查 | 已完成 |
| `fallback_planning_started` | 增强规划 | 开始执行 |
| `fallback_planning_completed` | 增强规划 | 已完成 |
| `capability_routing_started` | 能力路由 | 开始执行 |
| `capability_routing_completed` | 能力路由 | 已完成 |
| `provider_execution_started` | 增强执行 | 开始执行 |
| `provider_initialization_started` | 模型初始化 | 开始初始化 |
| `provider_initialized` | 模型初始化 | 初始化完成（Worker 已就绪） |
| `provider_task_started` | 任务执行 | 开始处理 |
| `provider_task_finished` | 任务完成 | 执行结束 |
| `provider_task_failed` | 任务失败 | 执行异常 |
| `provider_task_terminal` | 任务终结 | 已结束增强尝试 |
| `provider_execution_failed` | 增强失败 | 执行异常 |
| `provider_execution_finished` | 增强执行 | 已完成 |
| `canonical_started` | 结果构建 | 开始构建 Canonical |
| `canonical_completed` | 结果构建 | Canonical 构建完成 |
| `renderer_started` | 文档输出 | 开始生成 Markdown |
| `renderer_completed` | 文档输出 | Markdown 生成完成 |
| `audit_started` | 质量审计 | 开始执行 |
| `audit_completed` | 质量审计 | 已完成 |
| `result_writing_started` | 结果写出 | 开始写出 |
| `parse_finished` | 解析完成 | 处理结束 |
| `parse_failed` | 解析失败 | 处理异常 |
| `parse_heartbeat` | 运行心跳 | 仍在运行 |

任务完成根据原始 status 与 accepted 分别展示：

- SUCCESS + accepted=true：执行成功，结果已接受。
- SUCCESS + accepted=false：执行成功，结果未被接受。
- SUCCESS_WITH_WARNINGS：执行成功（有警告），仍单独显示是否接受。
- FAILED + accepted=false：执行失败，结果未被接受。
- 未知 status：执行结束，并保留原始状态；不把未知状态当成成功。

失败事件显示实际 current_phase。因此 provider_execution_failed 在初始化期间出现时，也能看到“阶段：模型初始化”；不会把初始化异常误写成任务完成。现有初始化完成事件实际表示 Worker READY，展示说明明确为“初始化完成（Worker 已就绪）”，不保证模型已在内部 execute 中完成加载。

Audit completed 没有 pass 字段，因此仅写“已完成”；HTTP 200、parse_finished 不意味着所有增强任务成功或 Audit 一定通过。Fallback completed 没有任务数时不显示虚构数量，待已有任务总数出现后才展示。没有独立阶段耗时字段，统一注明“累计运行”，只在 parse_finished 写“总耗时”。

## Provider 名称

| provider ID | 可读名称 |
|---|---|
| `rapidocr_ch_light` | RapidOCR |
| `paddleocr_v5_mobile` | PaddleOCR 文本 |
| `paddleocr_vl_16` | PaddleOCR-VL |
| `docling_local` | Docling |
| `mineru_local` | MinerU |
| `marker_local` | Marker |

始终保留 `provider_id=原始ID`。未知 Provider/phase 回退原始值；未知 event 用“运行事件”类别展示原英文代码。不存在或未知字段不会推断成页数、当前任务序号、ETA 或百分比。

## Formatter 与结构化兼容

Formatter 直接读取 LogRecord 属性，不解析/改写 JSON message，不修改 event 或任何记录字段，不持有跨事件状态。异常使用 formatException(exc_info) 追加 traceback，也不缓存修改 record.exc_text。

实时 Handler 仍在原位置一次 write、立即 flush 到 stderr，绕过普通解析 debug capture；不依赖 HTTP 响应返回。logger 的 propagate=False 与 Handler 个数保持，因此一个事件默认仅显示一次中文，不同时打印同一 JSON。

文件 Handler 没有配置中文 Formatter，现有 pipeline.log 与外部 collector 得到原英文 event、原字段和原 JSON 消息，机器接口可继续订阅 `pdffast.runtime.events`。异常文件日志仍沿用既有 traceback 表达。stdout/stderr 捕获与 Uvicorn access/error logger 未修改；第三方 Provider 子进程继承的 stderr 不经过中文 Formatter，保留其原始输出，不拦截或吞掉。

## 心跳、并发与异常

默认 30 秒、monotonic clock、last_progress 更新时机、ContextVar、线程/Event/锁、join/cleanup 完全不变。Formatter 只读取快照字段，没有回写状态或新增线程。

心跳区分模型初始化与增强执行；展示 task_elapsed_seconds 和 last_progress_elapsed_seconds，长任务仍写“正在执行”，不自动判定卡死。任务数来自已有 done/total，失败重试不伪装成完成。

每条事件包含运行编号、适用的 phase/provider/task。现有实时 Handler 的 logging 锁覆盖整块文本写出；并发测试验证每行 run/provider/task 对应一致，原并发结构化文件、状态和清理回归也继续通过。

异常保留 exception_type、原始 exception_message、provider/task、run 与阶段；不翻译或掩盖原始原因，显示完整 traceback。解析异常传播与 Provider escalation 不变。

## 前后展示对比与测试生成示例

原控制台（机器事件示意）：

```json
{"event":"parse_heartbeat","run_id":"api_demo","current_phase":"provider_execution","elapsed_seconds":120.0,"provider":"marker_local","task_id":"s9_demo","completed_tasks":0,"total_tasks":54,"task_elapsed_seconds":91.8,"last_progress_elapsed_seconds":91.8}
```

同字段经实际 Formatter 生成（示例数据，不是重跑 case_003）：

```text
[PDFFast][运行心跳] 正在执行 Marker | 运行编号：api_demo | 阶段：增强执行 | Provider：Marker（provider_id=marker_local） | 任务编号：s9_demo | 已完成任务：0/54 | 累计运行：120.0 秒 | 当前任务耗时：91.8 秒 | 距上次真实进展：91.8 秒
[PDFFast][任务完成] 执行成功，结果未被接受 | 运行编号：api_demo | 阶段：增强执行 | Provider：MinerU（provider_id=mineru_local） | 任务编号：s9_demo | 已完成任务：0/54 | 累计运行：140.5 秒 | 原始状态：SUCCESS
```

## 实测验证

新增 50 个展示用例覆盖所有 33 个既有 event、未知回退、6 个 Provider 名称、四种任务结果、长任务与初始化心跳、原始异常/traceback、结构化记录不变、无重复控制台、默认 30 秒、并发与 Audit 不臆造通过。首先验证旧实现无 Formatter 的失败，再实现并验证通过。

| 本轮验证 | 结果 |
|---|---|
| 中文展示 + 运行状态/心跳 + HTTP integration | 68 passed，0 failed |
| 完整 unit/contracts/regression | 390 passed，20 skipped，0 failed |
| reference-bound 完整回归 | 410 passed，0 skipped，0 failed |
| git diff --check | PASS |

v3 主环境没有 pytest，因此使用本机已有 `/Users/admin/Workspace/pdffast-v2/.venv/bin/python` 的测试依赖，通过 `PYTHONPATH` 指向 v3，并设置 `PYTHONDONTWRITEBYTECODE=1` 和 `-p no:cacheprovider`；未修改 v2。完整测试包含真实 FastAPI TestClient 的并发 HTTP v1 合同检查及原有 Canonical/Audit/Provider 回归；未启动重型 Provider。

reference-bound 使用 `/Users/admin/Workspace/pdffast` 与其 case_002.pdf。实际通过数量与冻结基线分开，本轮新增测试不删除旧测试；唯一更新的旧断言是已经明确调整的控制台表示合同。

## 剩余风险与人工验证

- 正在运行的服务需重新加载/重启后才使用新 Formatter。本轮不干预已有长任务。
- 建议在下一次正常 HTTP 使用时，人工观察中文长度、终端换行、第三方 stderr 混排与异常 traceback 可读性；不要求为展示重跑完整 66 页。
- 输出按已有字段展示。缺少独立阶段耗时、Audit pass 或 Provider 内部模型加载状态时不补造数据；这些限制来自现有事件合同，不在本轮新增状态。
- 若外部采集器此前从终端 JSON 解析状态，需改读保留的结构化 pipeline.log 或订阅命名 logger 的 LogRecord；默认终端现在是中文，尚未实现 JudgeAI 集成或状态 endpoint。

完成到此停止。
