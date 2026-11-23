# PDFFast V1 进程监管验收

## 当前进程架构与原问题

| 核查项 | 结论 |
| --- | --- |
| 谁创建 Worker | JudgeAI 的嵌入适配器创建 Core。Core 在 `fallback/executor.py` 初始化 Provider，`providers/workers.py` 创建隔离 Python Worker。Indra 和 MinerU 采用该路径，RapidOCR 在 Core 进程内运行。依赖探测也由 Core 创建短时子进程。 |
| 旧进程归属 | JudgeAI 以 `start_new_session=True` 创建 Core。原 `JsonLineWorker.start()` 对每个隔离 Worker 再创建独立 session，Worker 各自是其 PGID/SID 组长。JudgeAI 的 `killpg(core_pid)` 因而覆盖不到这些 Worker。 |
| 孙进程 | 合成故障测试实际创建 Worker 的模型孙进程。真实 `case_001` 在推理期间也观察到孙进程。PID、PPID、PGID、SID 和启动时间通过 macOS libproc 与 `getsid` 核对。 |
| 正常和协作清理 | Executor 在 `finally` 逐 Provider 关闭。锁定 Worker 要求 BYE 和实际退出码 0，轮询响应和退出时检查取消。Core 在清理成功、Audit 通过后才发布最终 manifest。 |
| 异常回收责任 | 新独立 Supervisor 等待 Core 的内核退出事件。Core 收到 SIGABRT 或 SIGKILL 后，即使 Python 无法执行清理，仍可回收同一 session 的 Provider 和模型进程。 |
| 调用方退出 | Supervisor 独立于 JudgeAI 的 session，且监听只有调用方持有写端的存活管道。写端随调用方退出关闭后，Supervisor 开始取消与回收。Supervisor 自己被 SIGKILL 时需要另有独立监管。 |
| 信号归属与等待 | Supervisor 创建专属 session，以尚未回收的直接 Core 子进程 PID 作为 PGID 锚点，仅对该专属组发信号。超时或取消先向 Core 发 TERM，Core 协作预算 2.5 秒，剩余组 TERM 预算 0.25 秒，KILL 后最多观察 1.0 秒。 |
| 子进程退出 | Supervisor 通过 `wait()` 回收直接 Core。Core 正常回收直接 Worker，Worker 正常回收它创建的模型子进程。异常时，对组内活进程发送信号并确认无在运行成员，由 macOS 接管并回收已失去父进程的后代。 |

原路径复现使用真实 `JsonLineWorker` 类和合成任务。外部控制器核对归属后向 Core 发信号，等待其 OS 退出，再核对 Worker 的原始启动身份。SIGABRT 组为 Core PID/PGID/SID `98693/98693/98693`，Worker `98694/98694/98694`。SIGKILL 组为 Core `98697/98697/98697`，Worker `98698/98698/98698`。两组在 Core 退出后都观测到 Worker 存活，由测试控制器按创建身份清理。

## 实现与边界

| 文件 | 修改 |
| --- | --- |
| `pdffast/process_supervisor.py` | 独立 macOS Supervisor 及 CLI。启动门闩保证在注册 `kqueue NOTE_EXIT` 和校验 PGID/SID 之后 Core 才 exec。直到组信号处理完成才回收 Core，避免 PGID 重用。libproc 复核组内活进程。合并后的 Core stdout/stderr 写入独占新日志，Supervisor 的 stdout 仅输出最终 JSON。 |
| `pdffast/providers/workers.py` | 验证 Supervisor 注入的 Core 身份。受监管的锁定 Worker 和其 Python Popen 子进程继承当前 run PGID/SID。共享组由 Supervisor 操作，Core 协作取消仅管理自己创建的 Worker 与已核验后代。Worker 退出判定结合直接子进程 OS 状态，避免孙进程持有 stdout 时一直等待 EOF。启动包装单独编译 Worker 源，兼容 Indra 的 `__future__` 声明。 |
| `scripts/verify_process_supervision.py` | 独立控制器、合成 Core/Worker/模型子进程、A–J 故障注入与 JSONL 证据。外部控制器只信号本次创建并核过身份的进程。 |
| `tests/unit/test_process_supervision.py` | 固化故障矩阵、并发隔离、非零退出和旧日志保护。 |

锁定 Profile、指纹算法与 provenance Schema 沿用 V1。源码修改会正常改变源码 SHA 和候选有效指纹。Supervisor 报告承载 OS 结果和资源状态，由上层在复核 V1 产物前消费。

正常结果需同时满足 Supervisor 实际退出码 0、最终 JSON 的 `reason=CORE_EXITED`、`core_returncode=0`、`cleanup_complete=true` 且 `accepted_exit=true`。Core 退出时若发现残留，即使清理完成也拒绝接受原本的退出 0。随后仍须按 V1 合同校验新 run ID、输入 SHA、Audit、provenance 与部署 pin。拒绝旧日志，输出目录仍由锁定 Core 的独占 run ID 约束。

合并到普通文件的 Core 日志不依赖 stdout/stderr 的管道 EOF 才能取得 Core 的退出状态。测试的合成孙进程继承内部 Worker stdout，H 在这种条件下仍取得 Worker OS 退出码 7。正常 Worker 响应和合法 Provider 回退继续沿用执行器逻辑。

## 平台与故障矩阵

本轮实测 macOS 14.6.1 arm64、CPython 3.12.13。当前实现显式限定 Darwin。Linux、Windows、目标生产镜像及任何操作系统级监督均需单独验证。进程组覆盖经验证的锁定 Provider 启动路径及继承进程组的后代。若第三方原生组件主动用系统调用脱离 session，本机制无法把任意进程限制回原组。新增这种组件前需验证等效隔离与回收。

最终故障证据为 `/tmp/pdffast-v1-supervision.EPQwVzDM/faults.jsonl`。例如 C 中 Supervisor 为 1283，Core、Worker、模型孙进程分别为 1284、1285、1286，三者 PGID/SID 均为 1284。真实 `case_001` 的推理中间采样显示 Core 1496、两个直接隔离进程 1563 和 1591，以及 1591 的子进程 1609、1610，PGID/SID 均为 1496。清理计时从 Supervisor 开始处理退出、取消或超时到返回验证结果。

| 场景 | 实际结果 | 清理耗时 |
| --- | --- | ---: |
| A 正常退出 | PASS。Core 0，全部已清理，接受退出。 | 0.0021 s |
| B 协作取消 | PASS。外部向 Supervisor 发 TERM，Core 17，全部已清理。 | 0.1103 s |
| C Provider 初始化时 Core SIGABRT | PASS。控制器在 Worker READY 前向 Core 发信号，Core -6，回收全部。 | 0.2595 s |
| D 推理时 Core SIGKILL | PASS。外部向 Core 发信号，Core -9，回收全部。 | 0.2572 s |
| E 产物写出后 Core SIGABRT | PASS。合成 Markdown 和 manifest 留存，Core -6，Supervisor 拒绝接受。 | 0.2557 s |
| F 外部时限终止 | PASS。Core 忽略 TERM，Supervisor 升级到组清理，Core -9。总耗时 4.0573 s，含 1.3 s 任务时限。 | 2.7567 s |
| G 并发隔离 | PASS。强杀作业的 Core -9。另一组 Core、Worker 和孙进程保持存活，释放后其 Core 0 并完成清理。 | 0.2627 s（受影响作业） |
| H Worker 非零退出 | PASS。Worker 实际退出 7，即使孙进程持有管道，Core 仍以 27 失败，组已清空。 | 0.0025 s（Core 退出后） |
| I 部分 Worker 已退出 | PASS。核对首个 Worker 已退、第二个仍活后强杀 Core，Core -9，回收剩余组。 | 0.2607 s |
| J_OWNER 调用方 SIGKILL | PASS。真实存活写端进程被强杀，独立 Supervisor 收到 EOF，Core 17，组清空。 | 0.1085 s |
| J Supervisor 自身 SIGKILL | FAIL。观测到 Worker 仍存活，只有测试控制器按原始创建身份清理。无 Supervisor 成功 JSON。 | 不适用 |

定向测试 121 passed、1 skipped，跳过项缺历史参考仓库设置。覆盖 Worker 生命周期、独立故障、并发隔离、Profile 闭包、Native-only 和 provenance。`git diff --check` 通过。

真实 `case_001` 以 Supervisor 包裹 `scripts.verify_production_governance --child` 复跑，47.4272 秒总耗时，Core 0，清理 0.0029 秒，剩余进程 0。30 页、19 个规划任务、三种 Provider 均产生选中结果，Audit 与 V1 输入及来源校验通过。首次真实复跑发现的 Indra 启动语法错误已修复并纳入合成 Worker 回归。该真实验收为未提交候选，正式 pin 需从获批 clean Commit 重建。

## JudgeAI 接入需求

需要调整 JudgeAI 的进程启动与终态判定，V1 业务字段接线沿用现有实现。本轮只读审阅了 JudgeAI，接入验收仍待执行。

1. 每次运行建立独立匿名存活管道 `owner_read, owner_write = os.pipe()`，用 `Popen(..., start_new_session=True, pass_fds=(owner_read,))` 启动 Supervisor。JudgeAI 关闭本地读端，独占写端，保持写端不可继承且不写数据。Supervisor 只持读端。Supervisor 启动 Core 时关闭该读端的继承。
2. 由已锁定的 PDFFast Python 启动 Supervisor，传入有限的正超时、全新绝对日志路径、`--owner-fd` 和现有 embedded runner 命令。`--` 之后的参数按原样传给 Core。项目根、V1 pin、输入、输出根和 run ID 都沿用当前受信调用路径。Supervisor stdout 只读一个最终 JSON 对象。
3. 用户取消时向 Supervisor PID 发 SIGTERM，或关闭写端触发 EOF，并等待其回收。任务超时由 Supervisor 负责升级，JudgeAI 等它返回。5 秒宽限期从取消或任务超时触发时开始。若 Supervisor 失败或未返回且外部监管已就绪，调用外部监管回收本次任务范围，禁止把无确认当成成功。
4. 验收拒绝 Supervisor 非零退出、响应缺失/损坏、Core 非零退出、异常原因或清理未确认。先判定进程终态，再读取本次最终 manifest 并执行现有 V1 检查。Supervisor 自身故障及目标生产平台必须通过部署级隔离验证。
5. 以真实 JudgeAI 调用在目标系统重做 A–J，确认取消宽限、并发和缓存命中前的失败处理。目标为 Linux 时使用其平台可验证的进程监管实现并单独验收，当前 Darwin 实现将拒绝运行。

### 复制给 JudgeAI Codex 的提示词

> 在 JudgeAI 的 PDFFast V1 独立工作区实现进程监管接入，保持 V1 Profile、指纹、provenance、缓存和 Alembic 合同。先只读审阅 `backend/app/integrations/pdffast_embedded_adapter.py` 的 `_execute` 和 `_stop_process`，以及 embedded runner 的 SIGTERM/cancellable_parse 路径。PDFFast 端使用 `python -m pdffast.process_supervisor --timeout SECONDS --log ABSOLUTE_NEW_LOG --owner-fd READ_FD -- <existing_core_command...>`，仅在已验收的 Darwin 环境启用该实现。JudgeAI 启动独立 session 的 Supervisor，只向它传入专属匿名管道读端，JudgeAI 独占不可继承的写端。让 Supervisor 负责 timeout 和 Core/Worker 组回收，取消时用 TERM 或 EOF，等待最多 5 秒，再交由目标环境的独立任务监管处理失败。只有 Supervisor 退出 0 且 JSON 的 reason 为 CORE_EXITED、core_returncode 为 0、cleanup_complete 和 accepted_exit 均为 true 时，才执行现有 run ID、PDF SHA、Audit、provenance 和 pin 校验。测试外部 SIGABRT/SIGKILL、超时、父调用方被杀、Supervisor 被杀、并发隔离、Worker 异常和已写产物后异常退出。目标系统必须证明 Supervisor 停止后仍可按任务范围回收后代。保持 WAITING_FOR_PDFFAST_RELEASE，待获批新发布身份与部署门禁均完成后才解锁。

## 复现命令

从 PDFFast 仓库根目录执行，证据目录为新目录。故障脚本输出 J 的 `NOT_PROTECTED` 表示复现了当前限制。

```bash
review_root="$(mktemp -d /tmp/pdffast-process-review.XXXXXXXX)"
export PYTHONDONTWRITEBYTECODE=1
.venv/bin/python -B -m scripts.verify_process_supervision "$review_root/faults" \
  > "$review_root/faults.jsonl"

.venv/bin/python -B -m pytest -q -p no:cacheprovider \
  tests/unit/test_process_supervision.py tests/unit/test_provider_lifecycle.py \
  tests/unit/test_provider_profiles.py tests/unit/test_production_preflight.py \
  tests/unit/test_parser_provenance.py tests/unit/test_native_only_provider_plan.py \
  tests/unit/test_fallback_executor.py tests/contracts/test_frozen_configs.py

git diff --check
```

同一证据目录可新增真实解析结果。该命令使用现有生产验收脚本的 Core 子命令。

```bash
profile="configs/profiles/production.indra-triple.json"
pdf="/Users/admin/Workspace/resource/case_001.pdf"
.venv/bin/python -B -m pdffast.process_supervisor \
  --timeout 420 --log "$review_root/pdf.log" -- \
  .venv/bin/python -B -m scripts.verify_production_governance \
  --child --project-root "$PWD" --provider-profile "$profile" \
  --output-root "$review_root" --run-id case_001 --pdf "$pdf" \
  > "$review_root/pdf-supervisor.json"
```

## 发布门禁

| 指标 | 结论 |
| --- | --- |
| CORE_SIGABRT_CLEANUP | **PASS**，macOS，独立 Supervisor 存活且组归属已核验。 |
| CORE_SIGKILL_CLEANUP | **PASS**，macOS，同上。 |
| SUPERVISOR_FAILURE_CLEANUP | **FAIL**，Supervisor 自身 SIGKILL 后观测到残留。JudgeAI 调用方死亡与此分开验证，存活管道 EOF 场景通过。 |
| CONCURRENT_ISOLATION | **PASS**，macOS，另一任务及其子进程持续运行并正常退出。 |
| RELEASE_GATE | **BLOCKED**。当前仍为 `NOT_READY`。JudgeAI 接入、目标平台及独立监督自身失败后的回收尚待证明。 |

PDFFast 工作区 HEAD 为 `63eeff3721b9b3de2acdc4de7df75bc9e61477f6`，本轮变更留在原工作区等待审批。真实 PDF 和历史验收证据按原位置保留。
