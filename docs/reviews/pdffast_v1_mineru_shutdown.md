# PDFFast V1 P0-A — macOS MinerU 正常关闭

验证环境为 macOS 14.6.1 arm64，Core 和 MinerU 均使用现有 Python 3.12.13。独立环境中的 MinerU 为 3.4.5，ONNX Runtime 为 1.30.0，构建提交 `f2c39fe`。导入 MinerU pipeline 后，用 dyld 实际映射表确认 ONNX Runtime Python 原生映像为 `runtimes/mineru/.venv/lib/python3.12/site-packages/onnxruntime/capi/onnxruntime_pybind11_state.so`。其 UUID `DFC50BF9-403D-3B27-AB58-182C9389C0F2` 与原崩溃报告一致。同目录的 `libonnxruntime.1.30.0.dylib` 存在，此 Python 导入的 dyld 映射表中只有 PyBind 映像。

## 崩溃与退出顺序

原 Job 的 Core PID 24953，MinerU PID 25055。Worker 已推理并回传 `BYE`，随后操作系统报告 SIGABRT。macOS 崩溃报告 `python3.12-2026-11-23-111435.ips` 中，故障线程在 `WorkerThread::threadFunc → HttpClientManager::onHttpResponse → HttpResponseDecoder → LogManagerImpl → DebugEventSource::DispatchEvent → recursive_mutex::lock`。这把故障定位到退出期间的 ORT 原生 1DS 遥测回调。单个崩溃栈不足以确定哪个对象先析构。

Worker 的 `close` 命令先回传 `BYE`，随后退出协议循环，让解释器自然结束。MinerU 3.4.5 的 pipeline 缓存按进程持有模型，其中表格分类和识别使用 ORT session。PDF 渲染进程池有自己的 `atexit` 回收，输出线程由 `ThreadPoolExecutor` 上下文收尾。原崩溃栈没有指向上述 Python 清理代码。保持它们原有顺序，Core 继续等待 Worker 的实际退出状态。

ONNX Runtime #24579 和 #25038 说明更早版本也有 macOS 退出互斥锁故障。#25038 的报告在主线程，不能用来证明本次回调线程的具体析构竞态。上游的 1DS 文档明确区分启动前 opt-out 与导入后的 API，后者只能抑制非必要事件，初始化事件仍可能先发生。 [#24579](https://github.com/microsoft/onnxruntime/issues/24579?timeline_page=1) · [#25038](https://github.com/microsoft/onnxruntime/issues/25038) · [ORT 遥测文档](https://github.com/microsoft/onnxruntime/blob/main/docs/Privacy.md)

## 最小修复与验证

仅在 Darwin 的 MinerU Worker 工厂将 `ORT_DISABLE_TELEMETRY=1` 放入隔离子进程环境，覆盖普通 Worker 和依赖探测。开关在任一子解释器导入 ORT 前生效。父进程及其他 Provider 环境保持原样。删除该工厂覆写即可回滚。未改依赖版本、模型、Worker 协议、PR1～PR3 wire 合同或成功回执条件。

本轮对照使用当前已安装的 MinerU pipeline。每个试验独立启动 Worker、执行真实推理、读出非空 OCR 文本并自然关闭。使用同一份输入图与模型。默认、启动前环境变量及导入后立即 API 调用三组交错执行。另用同一安装中的 MinerU 表格 ONNX 模型做 ORT-only 对照，改变推理完成到进程退出的间隔。正式结果与指标附在下方。

复跑真实 Worker 对照时，目录必须事先不存在。控制组会按所选模式在实验子进程中恢复默认遥测或测试最早 API。成功以真实推理、BYE 和 OS 退出 0 联合判定。每次试验单独写入 `trials.jsonl`。

```bash
.venv/bin/python -B -m scripts.verify_mineru_shutdown \
  --output-root "$EVIDENCE_ROOT/mineru-candidate" --count 30 --jobs 2
.venv/bin/python -B -m scripts.verify_mineru_shutdown \
  --output-root "$EVIDENCE_ROOT/mineru-comparison" --count 16 --jobs 2 \
  --modes baseline env api
```

| 对照 | 启动与真实推理完成 | 正常关闭退出 0 | 关闭后 SIGABRT |
| --- | ---: | ---: | ---: |
| 默认遥测，初轮加重复组 | 40/40 | 40/40 | 0 |
| 启动前 `ORT_DISABLE_TELEMETRY=1` | 16/16 | 16/16 | 0 |
| 导入后立即调用 `disable_telemetry_events()` | 16/16 | 15/16 | 1 |
| 候选默认路径，连续独立启动 | 30/30 | 30/30 | 0 |
| ORT-only，默认、启动前开关、导入后 API | 每组 20/20 | 每组 20/20 | 0 |

API-only 第 12 次（PID 33830）推理成功并返回 `BYE`，实际退出为 `-6`，stderr 再次出现 `recursive_mutex lock failed: Invalid argument`。因此导入后调用 API 不能作为本次修复。当前默认组未再触发，先前 launchd 默认为一次明确实测故障。启动前禁用的候选通过 30 次独立端到端试验和本机受管解析。这个结果支持规避已定位的遥测路径，仍不足以估计默认故障率或证明上游析构竞态已消失。

受管 `case_001` 完成 30 页、19 个规划任务，MinerU 实际尝试 5 次并选中 1 次。Native-only 完成 2 页、0 个规划任务。两份输入 SHA、Audit、V1 identity 和 provenance Schema、launchd 成功回执及组清理均通过。MinerU 生命周期、冻结 Profile、预检与 provenance 等定向测试共 118 项通过。

本机证据目录为 `/private/tmp/pdffast-p0-mineru.Yn2QH0Uw`。其中 `dyld.json` 与 `crash-excerpt.json` 保留库和栈证据，`comparison.log`、`default-repeat.log`、`candidate.log` 和 `ort-only.log` 逐试验记录，`closed-source-pdf` 保存两项 P0 最终源码的受管 PDF 回执和验收产物。

**`MINERU_SHUTDOWN_STABILITY = PASS`**，结论适用于本机和本次验收样本。
