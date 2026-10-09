# Uvicorn 服务退出与 Worker 生命周期可靠性

## 结论与证据边界

本轮确认并修复局部可复现的退出缺陷；没有证据证明其就是历史 case_003 Ctrl+C 问题的唯一根因。没有重跑 case_003、重型模型，未修改 v2、JudgeAI 或 8010 服务。

实际读取 service/app.py、ParseService、pipeline runner、runtime、Provider Registry、workers、executor、既有生命周期测试及 refactor-closeout-audit.md，并检查当前安装 Uvicorn 的关闭实现。Uvicorn 默认 graceful timeout=None，会先等待请求，再调用 lifespan。等待正在解析的请求本身不是泄漏。

## 已确认原因与最小修复

1. Worker select 就绪后调用阻塞 readline：只有半行 JSON 时无法落实响应超时。故障注入原 .4 秒超时仍在 1.2 秒等待；释放测试 Worker 后才退出。改为 os.read 增量读取、统一 monotonic deadline，保留多行缓冲；EOF 前捕获已拥有子进程身份，失败时回收。
2. Provider 初始化成功后才进入所有权 map：初始化失败可能跳过 close。现在 create 后立即登记，preflight/initialize 失败也清理。
3. 某 Provider close 抛错导致后续 Provider 未关闭：现在逐个尝试全部 close，明确记录 provider_cleanup_failed；保留原始执行异常，无原始异常时传播清理错误。
4. HTTP 任务取消不等于同步解析线程停止：每次请求独立取消 Event，阶段边界与 Worker 等待响应检测。ParseCancelledError 属于内部 BaseException，不能被普通 Provider 失败恢复逻辑吞掉并升级处理。取消请求不伪装成功。
5. SIGTERM 在 graceful deadline 后可于解析线程回收前退出：真实测试曾发现 Worker 遗留。service lifespan 持有现有解析 operation task，发出取消并等待清理完成；不是新增 Worker 管理系统。
6. 预检 subprocess.run 忽略取消：新增测试先复现，再改 owned Popen communicate 有界轮询，取消/超时 finally terminate→wait→kill→wait，并关闭 stdout/stderr。

## 关闭策略

新启动入口 `python -m pdffast.service`，默认127.0.0.1:8020，PDFFAST_SHUTDOWN_GRACE_SECONDS 默认30秒；PDFFAST_SHUTDOWN_CLEANUP_SECONDS 默认30秒，两者要求有限正数。使用原 Uvicorn CLI 时需要显式 `--timeout-graceful-shutdown 30`，其原默认行为没有被全局改变。

宽限期内正常完成请求，继续返回原HTTP v1；超过期限取消本请求，Worker 等待/预检响应取消，Provider finally清理，observation finally停止并join原心跳。lifespan最多等待配置的清理窗口，未完成时记录run_id与原因。

**限制：**进程内 Native/C 调用无法安全强制中断，只能在阶段边界检查。lifespan等待有界不等于任意Native死锁下整个Python进程退出有界；executor线程退出仍可能等待。没有通过误杀共享进程解决这一问题。SIGKILL也不保证finally执行。真实重型Provider内部永久阻塞仍需单独复现/进程隔离方案，本轮不扩大架构。

## 真实信号/进程测试

真实Uvicorn、真实HTTP adapter、真实JsonLineWorker；模型推理采用小型故障注入协议。short模式对生成的一页PDF实际运行Profiler，但后续结果为测试替身，不代表完整生产模型推理验收。各场景使用随机端口且禁止8010，仅操作测试自己创建的PID。父子关系记录在worker.json。SIGTERM退出码-15来自Uvicorn退出后重发信号，不代表Worker未回收。

| 场景 | Server PID | Worker PID | 端口 | 信号 | 信号后退出秒 | 端口释放 | Worker回收 |
|---|---:|---:|---:|---|---:|---|---|
| idle | 89155 | — | 59728 | SIGINT | 0.238 | YES | YES |
| short | 89161 | — | 59744 | SIGINT | 0.234 | YES | YES |
| worker timeout | 89162 | 89163 | 59760 | SIGINT | 0.493 | YES | YES |
| worker timeout | 89168 | 89169 | 59780 | SIGTERM | 0.444 | YES | YES |
| partial JSON | 89176 | 89177 | 59795 | SIGINT | 0.562 | YES | YES |
| worker cancelled | 89182 | 89185 | 59819 | SIGINT | 0.619 | YES | YES |
| worker cancelled | 89201 | 89203 | 59851 | SIGTERM | 0.561 | YES | YES |
| graceful completed | 89204 | 89210 | 59884 | SIGINT | 0.234 | YES | YES |
| initialize failed | 89211 | 89212 | 59906 | SIGINT | 0.184 | YES | YES |
| execute failed | 89213 | 89214 | 59922 | SIGTERM | 0.130 | YES | YES |

证据保存在 outputs/service_shutdown_validation/20261009-final/，包括每例evidence.json与server.log。宽限期内完成与short结果HTTP200/schema_version=1.0；超时、失败及主动取消返回非成功，不以HTTP200伪装任务成功。

## 修改范围

- pdffast/providers/workers.py：部分JSON超时、协作取消、预检探测清理。
- pdffast/fallback/executor.py：早期ownership、全部close与异常保留。
- pdffast/runtime.py：请求范围取消上下文；已有心跳计时与进展语义不变。
- pdffast/runtime_format.py：集中增加资源清理失败中文事件。
- pdffast/service/app.py：保持同步计算与返回字段，异步adapter持有并清理请求operation，lifespan等待。
- pdffast/service/__main__.py：显式有限grace启动入口。
- tests/unit/test_shutdown_cleanup.py、tests/unit/test_service_shutdown.py、tests/fixtures/service_shutdown_lab.py：故障注入、并发隔离、真实信号端口回收。
- 本报告及独立验证产物。原有大量未提交修改全部保留，不提交、不清理。

## 合同与隔离

HTTP路径、上传请求、schema_version、ParseResult及成功响应字段未变。Provider排序/路由/Acceptance、Canonical、Markdown、Audit、SupplementalEvidence、ArtifactPaths均不改。无需中间JSON回读，无Runtime File Bus。取消Event由各请求独立持有；并发测试取消一请求不影响另一个Worker及成功结果。已有中文logging保留traceback，清理失败独立记录Provider身份。没有新增心跳或监控线程。

## 本轮测试

- 定向shutdown cleanup及原Provider lifecycle：33 passed。
- 真实Uvicorn信号专项10种场景在完整套件中均通过；包含初始化失败、执行失败、timeout、半行JSON、SIGINT/SIGTERM、宽限期完成、端口释放。
- 完整 tests/unit tests/contracts tests/regression：440 passed、20 skipped、0 failed，35.45秒。20 skipped均为reference变量未提供。
- reference-bound全套：460 passed、0 failed，148.74秒；PDFFAST_REFERENCE_ROOT=/Users/admin/Workspace/pdffast，PDFFAST_SAMPLE_PDF指向case_002。
- git diff --check：最终再次执行通过。

测试使用已安装测试依赖的只读 /Users/admin/Workspace/pdffast-v2/.venv/bin/python，PYTHONPATH指向v3，禁用pyc/cacheprovider；未写v2。socket测试经批准绑定隔离端口，未因sandbox而跳过。未运行完整case_003。

## 剩余风险与下一步

历史真实模型Ctrl+C问题尚不能唯一归因；应在独立环境使用新有限grace入口人工验证现有真实模型任务，不需要先跑完整case_003。Native/C永久阻塞属于未覆盖边界。重复强制信号可能跳过应用清理；本轮验证单次正常关闭信号。取消并不提供新的HTTP取消状态合同，客户端可能看到500或断开。不要将进程终止或Acceptance/Audit PASS等同于内容真实性。

完成场景的finished.json记录无pdffast-heartbeat-*线程；取消/失败路径通过专项测试断言心跳结束。现存通用AnyIO/ThreadPoolExecutor线程属于服务线程池，主进程随后退出，不是遗留心跳线程。所有10例父子PID关系、信号、退出时间、端口及worker_reaped结果已保存。没有使用全局pkill/killall。
