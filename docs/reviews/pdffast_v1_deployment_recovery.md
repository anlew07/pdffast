# PDFFast V1 部署级进程回收

## 结论与目标环境

**`RELEASE_GATE = BLOCKED`，发布状态为 `NOT_READY`。** macOS 的同组回收已通过真实临时 Job 验收。主动创建独立 session 的负向用例仍有残留，正式部署平台及 JudgeAI 端到端接入也待确认。

实测机器是 macOS 14.6.1（23G93）arm64、Python 3.12.13。只读检查确认本机 `launchctl print`、`bootstrap`、`kill` 和 `bootout` 可用，GUI 用户域实际运行临时 Job。PDFFast README 和既有验收文档列出 macOS 本机证据与 Linux 离线差距，JudgeAI 同时保有原生部署与 Linux Docker 文档。仓库中未找到获批的 PDFFast V1 正式生产 OS、服务账号或 launchd 域。

临时 Job 涉及当前用户域、随机标签和临时文件，测试后按该标签卸载。系统和用户的持久 launchd 配置没有变更。

## 任务身份与责任边界

每次 `prepare` 生成独立 UUID。进程组由 launchd 管理，标签为 `local.pdffast.v1.<UUID>`。Supervisor 是 Job 组长，Core、Indra / MinerU Worker、已观察到的模型孙进程以及一个轻量组内清理进程继承该 PGID。RapidOCR 保持在 Core 中运行。Driver 发起信号时核验 launchd 返回的 plist 路径，操作的是完整 Job 标签。持久文件里的 PID、PGID 和时间只用于诊断，控制器从不根据这些数字信号进程。

Apple 文档描述 `AbandonProcessGroup=false` 的同组回收边界。首次本机故障矩阵发现，只靠该行为仍可能留下一个忽略 TERM 的孙进程，发生在 Supervisor 初始化阶段被强杀时。现由组内清理进程持有存活管道的读端，Supervisor 独占写端。Core 开始前已核验清理进程就绪。Supervisor 被强杀时写端由内核关闭，清理进程在原组仍有活成员身份时向自己所在的组发 SIGKILL。正常路径只有看到 Core 退出、组中只剩自身和清理进程时才传解除字节。Core 和 Worker 均不继承写端。这样避免使用历史 PGID、等待已死亡的进程执行清理或按 Provider 名称查杀。 [Apple launchd.plist(5)](https://github.com/apple-oss-distributions/launchd/blob/main/man/launchd.plist.5)

| 组件 | 责任 |
| --- | --- |
| launchd | 持有独立 Job、由标签定位任务、提供启动与实际退出状态，并负责 Job 的停止边界。 |
| 组内清理进程 | 依赖内核管道 EOF 处理单次 Supervisor 死亡，忽略 TERM，只向自身所在任务组发 KILL。它与任务共用同一 Job。 |
| Supervisor / Core | 延续单次超时、协作取消、Worker 退出码、产物与 V1 合同。受管路径让 Worker 继承已经核验的 Job 组。 |
| 持久回收控制器 | `install-controller` 安装当前用户 LaunchAgent，使用 `RunAtLoad` 和 20 秒 `StartInterval` 周期执行 `reconcile-all`。Health 同时核验 plist 身份、launchd 加载状态和 60 秒内的成功扫描。控制器逐项读取持久意图，根据租约处理注册过期任务，只向 Manager 已验证的标签发 `bootout`。 |
| JudgeAI | 检查部署门禁，提交任务、读取回执并按现有 V1 合同复查本次产物。 |

### 登记、启动与恢复边界

1. 私有目录由部署账号持有且模式为 0700。每个运行由唯一目录与固定 plist 路径绑定。配置文件和 `plan.json` 按文件及目录 fsync 后发布。
2. `submit` 持有单任务锁，先写 `submitted.json`，再执行 launchd 注册。若进程在两步间退出，后续返回 `SUBMISSION_UNCONFIRMED`，同一任务不会自动重放。正式操作需查验同标签状态，并在能确认无活动范围后人工判定是否新建任务。
3. 受管进程核验 Manager 当前记录的标签、plist 路径和自身 PID，持久落下 `claimed.json` 后才进入 Supervisor。Supervisor 又等待任务组清理进程确认就绪才打开 Core 启动闩。登记写入失败时 Core 与 Worker 不启动。
4. 任务过期时先写 `stop.json`，再停止精确的 Job。控制器中断后，`reconcile-all` 扫描原目录并续做。不会用 PID 记录补发信号。
5. 成功需要 Supervisor 结果证明 Core 退出 0 且组已清理、launchd 确认 Job 退出 0，之后才生成 `completed.json`。完成记录可以在卸载已结束 Job 后持久验证。即使已有 Markdown、manifest 或内部 Supervisor 报告，异常退出和缺少完成回执仍失败。

`pdffast/deployment_recovery.py` 提供持久登记、单次提交和恢复扫描。`pdffast/process_supervisor.py` 增加受管组和存活管道清理。`pdffast/providers/workers.py` 绑定已核验的受管 PGID。验收集中在 `tests/unit/test_deployment_recovery.py`。V1 Profile、指纹算法、provenance 与两份 Schema 继续沿用。

## macOS 故障验证

清理时间从外部控制器发信号开始，包含本机 `launchctl` 调用和轮询确认。下列为本机观测值。协作取消 5 秒宽限仍单独由既有 Supervisor 定向回归验证，异常回收的生产 SLA 需要按目标机器、扫描周期和实际抖动重新测量。

| 场景 | 结果 |
| --- | --- |
| 推理中 Supervisor SIGKILL | PASS，0.0552 秒。Worker 及模型孙进程均已退出。实测 Job PGID 5972，Worker 5983、模型 5984，SID 都是 1。 |
| 初始化中 Supervisor SIGKILL | PASS，0.0568 秒。复测原来会留下拒绝 TERM 的模型孙进程，新的组内清理关闭该缺口。 |
| 产物生成后 Supervisor SIGABRT | PASS，0.0162 秒。合成 manifest 仍在，但缺成功回执，任务失败。 |
| 回收控制器自身被杀并重启 | PASS。外部在写入 `stop.json` 后、调用 `bootout` 前强杀控制器。新进程扫描原状态并回收已暂停 Job，重启后 1.1473 秒。此值不含生产定时扫描周期。 |
| 并发 Supervisor 强杀隔离 | PASS。两组 PGID 不同；受影响组清空，另一任务的原始进程身份持续存活，正常完成后连续读取同一成功回执。 |
| Worker 请求独立 session | 受支持的 Python Popen 路径被约束为继承 Job 组，并实测随组回收。绕过该路径主动脱离组的负向用例观察到残留，由测试控制器按创建时间核验并仅清理该测试子进程。 |
| 已登记、启动 Worker 前异常 | 有真实 Job 故障用例，记录已持久化，只有 Supervisor、清理进程和 Core，再强杀 Supervisor，三者退场且任务失败。 |
| Worker 已启动、登记未完成 | 持久 claim 写失败的故障注入证明 Core 启动入口未被调用；提交意图不确定时同一运行不重放。 |
| 已完成任务 | PASS。连续 reconcile 读取持久成功回执，重复提交被拒绝，独立异常 Job 的回收不改变结果。 |
| PID 重用 / 错误归属 | 模拟 stale PID 指向测试控制器自身，实际无信号；模拟同标签路径不匹配，拒绝进一步操作。未强制产生真实内核 PID 回收重用。 |

真实 `case_001` 也由临时 launchd Job 正常运行。耗时 48.8167 秒，最终回执为 `COMPLETED`，30 页、19 个规划任务、无组内残留，输入 SHA、Audit 和 V1 来源检查通过。候选证据位于 `/private/tmp/pdffast-launchd-smoke-kmu68_qp`。

最终定向回归 131 通过、1 跳过，包含 10 个临时用户 Job 验收用例、旧 Supervisor 与 Worker 生命周期、Profile 闭包、Native-only 和 provenance。跳过项缺历史参考仓库参数。`git diff --check` 通过。

## JudgeAI 最小接入合同

JudgeAI 需要改用已获批平台的部署后端，V1 业务接线沿用现有逻辑。本轮只做只读核查。

- **启动与健康**要求平台、域、部署账号、私有登记目录、周期恢复进程和目标环境验收记录均可核验。目标发布 Commit 和 V1 pin 也必须已批准。仅当部署门禁为 PASS 时才允许生产解析。
- **请求与等待**以受信配置构造原嵌入 runner 命令，通过 `prepare`、`submit` 登记，持久记录任务 UUID 并轮询 `reconcile`。Job 的环境来自 Manager，发布预检要在相同启动环境运行。
- **终态**只接受当前 UUID 的 `COMPLETED` 且 `accepted_exit=true`，随后复查 V1 manifest 的唯一 run ID、PDF SHA、Audit、授权身份与 provenance。启动、恢复、控制面不可用或回执不明均进入失败/阻断状态。JudgeAI 不维护 Provider PID 或名称清单，也不自动降级到旧无监管路径。
- **故障/取消**维护当前 5 秒协作等待语义，目标回收压力测试负责确定另一条异常 SLA。如果需要提前撤销在途任务，接入经批准的部署控制操作，按本次 UUID 记录停止意图并交由 Manager 回收。现有最小 CLI 自动路径覆盖已登记任务的租约到期。

## 安装、验证及回滚

### macOS 候选路径

1. 审批生产账号与 macOS 版本，选择经实测可用的当前用户 `gui/<uid>` 或 `user/<uid>`。本轮只验证 GUI 域；无登录会话环境、重启、登出和无头用户域均需重新实测。
2. 固定 release checkout、Python 和模型环境。由授权运维创建 0700 spool。Job 日志、输出使用每次运行的新绝对路径。在已受信 release checkout 中执行以下命令。周期扫描可由授权运维显式安装用户级 LaunchAgent，以 `RunAtLoad` 和经 SLA 验收的 `StartInterval` 调用 `reconcile-all`。当前仓库提供入口，安装由目标运维审批。
3. 按下面的 opt-in 指令重跑隔离故障集，并在实际 JudgeAI 用户、权限和启动链下验证全矩阵。目标部署仍需复测真实 Provider 的组归属、跨启动周期的租约恢复与收据保留、控制器及 Manager 故障后的结果判定。

```bash
# PY 指向发布 Python，ROOT 是已创建且属于当前部署账号的私有 spool
# DOMAIN 是已获批测试的当前用户域；CORE_LOG 是尚不存在的绝对路径
run="$("$PY" -B -m pdffast.deployment_recovery prepare \
  --state-root "$ROOT" --domain "$DOMAIN" --timeout 1800 \
  --log "$CORE_LOG" -- "$PY" -B "$APPROVED_CORE_RUNNER" "${core_args[@]}")"
"$PY" -B -m pdffast.deployment_recovery submit "$ROOT" "$run"
"$PY" -B -m pdffast.deployment_recovery reconcile "$ROOT" "$run"
"$PY" -B -m pdffast.deployment_recovery reconcile-all "$ROOT"
```

```bash
PDFFAST_TEST_LAUNCHD=1 PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest \
  -s -q -p no:cacheprovider tests/unit/test_deployment_recovery.py
git diff --check
```

回滚时先关闭生产接入门禁并停止受理新 Job。按登记目录核验待完成 Job 的精确标签和 plist 路径，等任务退场或由授权运维卸载该单任务 Job。终止后的 UUID 与回执留存，生产回滚版本仍须具有已证明的回收能力。周期 LaunchAgent 的移除在所有任务排空后单独执行。

### Linux 方案

在目标主机使用 cgroup v2 和 systemd 的单任务 service。申请唯一 unit 名与 InvocationID，记录它们及部署租约后才允许启动 Core。使用 `KillMode=control-group`、`SendSIGKILL=yes`、有限 `TimeoutStopSec` 和 `RuntimeMaxSec`，禁止任务把自己迁出 cgroup，控制器重启后按 unit 身份继续 stop 并核查实际退出状态。重新注入 SIGABRT、SIGKILL、控制器重启和 `setsid`，并确认 scope 已空。Linux 方案未在本机执行。 [systemd.kill](https://www.freedesktop.org/software/systemd/man/262/systemd.kill.html)

## 剩余门禁

- 确定正式生产 OS、服务账号、进程管理器和正式 PDFFast Commit。在目标环境验证真实 JudgeAI 接入后的完整矩阵，并保留跨重启、管理器故障、观测时钟漂移和并发证据。
- macOS 范围以 Job 进程组为限。若要求回收主动脱离该组的原生进程，当前候选不足以放行。应在实际 Provider 闭包中证明无此行为，或采用可执行范围级约束的平台，并在同一套故障用例中证明其回收。
- 双重故障（Supervisor 和组内清理进程同时被硬杀）、机器重启或用户登出，以及目标 SLA 未验收。持久租约当前用墙钟，需在目标时间同步和重启条件下验证异常恢复时限。
- 正式 pin 继续由获批 clean Commit 和受管运行环境生成。在上述目标验收前，JudgeAI 保持 `WAITING_FOR_PDFFAST_RELEASE`。工作区留存待审批。


## 2026-11-23 合并前 Worker 归属复核

本节保留 P0 修复前的归属证据和当时判定。最新合并状态见[两项 P0 最终验收](pdffast_v1_release_readiness.md#2026-11-23-两项-p0-最终验收)，现有部署控制接口见[接线合同](../contracts/deployment_control_v1.md)。

**`PDFFAST_CODE_MERGE_READY = NO`。** Worker 脱组修复与定向验收完成。MinerU 正常关闭期间复现间歇性的原生 SIGABRT，阻断安全合并。PR1～PR3 合同继续通过。

Worker 启动前根据 Supervisor 写入的本次 Core PID 核对当前进程身份。launchd Job 要求 Core 的 PGID 等于已登记的 Job PGID 和 Supervisor PID。独立 Supervisor 要求 Core 自己是 session 及进程组组长。两条路径的组归属均独立于 `locked_runtime`。新回归在修复前分别观察到 launchd 的 Worker PGID 20672、Core PGID 20658，以及独立 Supervisor 的 Worker PGID 25386、Core PGID 25385。修复后两种入口均由真实子进程证明 SID 与 PGID 相同。

直接执行 Core 时，Worker 继续以独立 session 启动，保留原有超时、信号和组级回收。真实直接启动对照中，Core PID、PGID、SID 均为 26972，Indra 为 27008，MinerU 为 27073。两者均在正常关闭后退场。受管路径由 Supervisor 负责整组回收，Worker 仍只向自己的进程和已验证身份的后代发信号。

### 真实模型与故障

在 macOS 14.6.1 arm64 的当前用户 GUI 域，通过临时 Job 运行三种实际 Provider。用内核记录核对 PID、PPID、PGID 和进程启动时间，并逐 PID 调用 `getsid`。MinerU 的 PDF 渲染子进程由 MinerU pipeline 的 `ProcessPoolExecutor` 启动，实测进程参数包含 `multiprocessing.spawn` 和 `spawn_main`。另观察到同组的 `multiprocessing.resource_tracker`。RapidOCR 在 Core 内执行。每个正常场景均实际推理并产出非空文本。

| 场景 | PID 及父子关系 | PGID / SID | 结果 |
| --- | --- | --- | --- |
| 正常结束，V1 锁定 | Core/RapidOCR 26134 → Indra 26141、MinerU 26167 → Renderer 26222，Tracker 26221 | 26131 / 1 | 三种推理成功，`COMPLETED`，退出 0，组清空。 |
| 正常结束，Worker 未锁定 | Core/RapidOCR 26359 → Indra 26372、MinerU 26398 → Renderer 26414，Tracker 26413 | 26356 / 1 | 三种推理成功，`COMPLETED`，退出 0，组清空。 |
| 推理中 Supervisor SIGKILL | Supervisor 26239，Core 26248 → MinerU 26276 → Renderer 26290，Tracker 26289 | 26239 / 1 | `FAILED`，观测到组清空约 0.051 秒。并发组 26131 的原始进程身份持续存活，随后正常完成。 |
| 推理中 Core SIGABRT | Core 26309 → MinerU 26334 → Renderer 26350，Tracker 26349 | 26306 / 1 | 对已核验启动时间的 Core PID 实际发 SIGABRT。约 0.038 秒组清空，`FAILED`。本次无内部 `result.json`，外部回执拒收。 |
| 另一次正常关闭 | Core 24953 → MinerU 25055 | 24950 / 1 | Worker 返回 BYE 后以 -6 退出，回执 `FAILED`。macOS 崩溃报告的 PID 与 MinerU 拓扑匹配。 |

失败运行中，Core 日志记录 `recursive_mutex lock failed: Invalid argument` 和 `WorkerShutdownError(stage=close, bye=True, returncode=-6)`。macOS 报告 `python3.12-2026-11-23-111435.ips` 显示 SIGABRT，崩溃线程经过 `onnxruntime_pybind11_state.so` 的 `Microsoft::Applications::Events` 事件分发栈及 `std::__1::recursive_mutex::lock()`。这是实测的栈位置，触发条件尚未定位。后续成功样本说明该异常具有间歇性。

合并前定向回归共 141 项通过。使用现有历史参考 checkout，通过冻结配置对照。受管 `case_001` 得到 30 页、19 个规划任务，三种 Provider 均有真实尝试与选中记录，PDF SHA、Audit、V1 来源及成功回执通过。Native-only 为 2 页、0 个 Provider 任务，Audit 和回执通过。两次解析的 identity 和 provenance 均通过 Draft 2020-12 校验。本轮重跑这两份，先前五份真实 PDF 的证据保留在发布审阅中。Ruff 的 72 项逐条对照见同目录的 `pdffast_v1_ruff_baseline.md`。

证据位于本机 `/private/tmp/pdffast-v1-closeout.rYSWxJpo`。其中 `complete-matrix` 有可复跑脚本、各 Job 拓扑和结果，`provider-final/live-normal` 有原生错误的 Core 日志和对应拓扑，`pdf-final/pdf-regression` 有最终源码的 PDF 报告，`cli-contract` 有公开 CLI 烟测的持久回执，`final-targets.log` 有定向回归完整输出。

### 调用约束与已知边界

- 使用仓库根目录作为 `prepare` 的工作目录，准备当前部署账号独占的 0700 spool 和每次运行的新绝对日志、输出路径。将 Core Python 作为待执行命令的首个绝对路径。用 `-m scripts.run_pipeline` 或可信嵌入 runner 直接在该 PID 内执行解析。如果入口是包装脚本，需用 `exec` 保留 PID。Supervisor 负责写入并验证内部归属标记。
- CLI `prepare` 输出 32 位运行 UUID。CLI 租约从 `prepare` 开始，默认 `timeout + 30` 秒。`submit` 只提交一次。`reconcile` 输出回执 JSON，CLI 返回 0 只表示查询成功。只有该 UUID 的 `COMPLETED` 与 `accepted_exit=true` 才可继续核对 V1 产物。`reconcile-all` 负责持久租约扫描。Manager 解析不到可核验终态时，缺失成功回执应按失败处理。
- macOS 回收以 Job 进程组为边界。隔离负向用例中的子进程主动创建 session，Supervisor SIGKILL 后仍存活，随后按该测试进程的原始身份清理。现有 Python Worker 包装只约束普通 `Popen` 的显式组和 session 参数。直接 `setsid`、原生脱组、受管组和清理进程同时失效等仍超出本次证明范围。
- 本机只实际验收 `gui/<uid>`。无头 `user/<uid>`、登出与重启、目标部署 SLA 和正式 JudgeAI 接入仍需在批准环境验证。
