# PDFFast macOS 部署控制合同 V1

控制报告使用字符串版本 `"1.0"`。[Health JSON Schema](deployment_health.v1.schema.json) 和 [Cancel JSON Schema](job_cancel.v1.schema.json) 可独立校验。解析配置身份和解析来源继续使用各自的 V1 合同。

## 调用环境

部署账号在 PDFFast checkout 根目录执行下列命令。所有控制进程使用同一部署解释器、工作目录、当前用户域和登记目录。`ROOT` 为已经创建、由当前账号独占的 `0700` 目录。`PY` 为部署解释器的绝对路径。`DOMAIN` 选用当前用户的 `gui/<uid>` 或 `user/<uid>`。部署前在实际目标域验证。

```bash
"$PY" -B -m pdffast.deployment_recovery install-controller --state-root "$ROOT" --domain "$DOMAIN"
"$PY" -B -m pdffast.deployment_recovery health --state-root "$ROOT" --domain "$DOMAIN" --json
"$PY" -B -m pdffast.deployment_recovery cancel "$ROOT" "$JOB_ID"
"$PY" -B -m pdffast.deployment_recovery reconcile "$ROOT" "$JOB_ID"
"$PY" -B -m pdffast.deployment_recovery reconcile-all "$ROOT"
```

`JOB_ID` 是 `prepare` 返回的 32 位小写十六进制 UUID。调用方应持久化它与解析 `CORE_RUN_ID` 的对应关系。两者独立生成和验证。登记目录包含本次运行的可信命令和日志路径，应按部署数据管理。调用方应以参数数组启动命令，并只用可信配置组装参数。

## 健康检查

一次正常调用在 stdout 输出一个 JSON 对象。`PASS` 退出 `0`，`BLOCKED` 退出 `1`。CLI 参数解析错误使用 `argparse` 的退出码 `2` 和 stderr。消费者应校验 JSON、Schema 版本、退出码和 `state`。

| 字段 | 语义 |
| --- | --- |
| `environment` | 操作系统、机器架构、系统内核版本、Python 版本、实际解释器路径、有效账号 UID、请求域及登记目录。 |
| `code_identity` | 从本次实际 PDFFast 源码计算的身份，字段同[解析配置身份 V1](production_parser_identity_v1.md)。身份无法计算时为 `null`。Git 工作树可能为 dirty，消费者按独立发布锁判定。 |
| `state_root` 检查 | 检查目录归属、私有权限和本次实际的持久登记能力。 |
| `launchd` 检查 | 实际查询指定当前用户域。 |
| `process_observation` 检查 | 验证本机可观察任务范围所需的进程能力。 |
| `controller` 检查 | 核对专用 LaunchAgent 已按当前 checkout、解释器和登记目录加载，且以 `RunAtLoad` 和 20 秒 `StartInterval` 周期执行；同时核对 `reconcile-all` 完成的近期扫描。扫描覆盖指定登记目录，包括其中登记的当前账号各用户域。扫描身份绑定当前系统启动标识、源码、Git Commit、解释器、工作目录、规范化登记目录路径和 UID。 |
| `recovery_probe` 检查 | 使用独立 UUID 对实际 launchd Job 执行启动和回收探测，并验证回收。探测启动短时 Core 与一个拒绝 TERM 的同组子进程。检查同组子进程实际加载的源码身份与调用方一致。核验归属后，向该探测 Job 的 Supervisor 发 SIGKILL，确认组清空并撤销登记。 |
| `code_identity` 检查 | 标记源码身份计算是否成功。 |

六项检查位于 `checks`。各项含 `status` 和 `code`。`status` 为 `PASS`、`BLOCKED` 或 `NOT_CHECKED`。仅在六项均通过时报告总体 `PASS`。`controller` 对象给出最近一次扫描的 Unix 时间、按单调时间计算的扫描年龄和 60 秒有效期。最近扫描可以处在运行中或失败状态，此时检查仍为 `BLOCKED`。数据缺失时，时间及年龄可能为 `null`。首次部署必须执行 `install-controller`；它安装当前用户的 `~/Library/LaunchAgents/local.pdffast.v1.reconcile.plist`，设置 `RunAtLoad=true` 和 `StartInterval=20`，并等待首次成功扫描。Health 会验证该 plist 内容、launchd 加载状态和近期 heartbeat；仅手工运行一次 `reconcile-all` 不足以使 Health 通过。维护或卸载时执行 `uninstall-controller`。安装后由 launchd 持续调度，不再依赖外部 cron 或人工轮询。

| 检查 | 可能的 `code` |
| --- | --- |
| `state_root` | `STATE_ROOT_INVALID`、`STATE_ROOT_IO_ERROR` |
| `launchd` | `UNSUPPORTED_PLATFORM`、`LAUNCHD_UNAVAILABLE` |
| `process_observation` | `PROCESS_OBSERVATION_UNAVAILABLE` |
| `code_identity` | `CODE_IDENTITY_UNAVAILABLE` |
| `controller` | `BOOT_ID_UNAVAILABLE`、`SWEEP_MISSING`、`SWEEP_IDENTITY_MISMATCH`、`SWEEP_INVALID`、`SWEEP_STALE`、`SWEEP_NOT_SUCCESSFUL` |
| `recovery_probe` | `CANARY_SCOPE_INVALID`、`CANARY_CODE_IDENTITY_MISMATCH`、`CANARY_CLEANUP_UNVERIFIED`、`CANARY_FAILED`、`DEADLINE_EXCEEDED`、`LAUNCHD_UNAVAILABLE`、`JOB_OWNERSHIP_MISMATCH`、`PROCESS_OBSERVATION_UNAVAILABLE` |

JudgeAI 应当使用自己已批准的发布锁核对环境身份及代码身份，并按原合同运行配置、模型预检和 provenance 校验。Health 的 `PASS` 表示部署控制检查通过。发布批准、Provider 推理可用性和解析结果由各自门禁决定。

## 按 Job 取消

控制器在本次 UUID 的运行锁内原子写入持久取消意图。Core 启动门与取消意图共用同一把锁。意图先持久化时，Core 不会越过启动门。已启动的 Core 进入协作取消。需要进一步回收时，控制器核验 launchd 标签绑定到本次登记的 plist，随后仅对该 Job 执行卸载。已持久完成的任务保持原有完成回执，可以继续按既有流程验收。

取消控制尝试使用 4.75 秒的进程内预算，为 JudgeAI 的五秒调用窗口预留启动时间。当前 Supervisor 向 Core 发 SIGTERM 后最多等待 2.5 秒。只有安装了相应信号处理器的 Core 入口能在此期间执行协作取消。仓库的 `scripts.run_pipeline` 沿用 SIGTERM 默认退出行为。取消意图落盘约三秒后仍有活动 Job 时，控制器进入 launchd 强制回收及核验。达到预算仍未证实清理时，调用方按返回状态继续轮询。系统调用、调度和磁盘写入耗时不受应用层强实时约束。

提交结果不明确时保留取消意图，阻止旧 UUID 再次提交和打开 Core 启动门。遇到尚未观察到的登记，调用方可执行 `reconcile` 或等待定期 `reconcile-all` 处理迟到的登记和租约。重试必须使用原 UUID。取消的内部记录与成功完成记录都由 PDFFast 持久化，调用方应使用 CLI 读取结果。

| `state` | 退出码 | JudgeAI 处理 |
| --- | --- | --- |
| `CANCELLED` | `0` | `accepted_exit=false`、`cleanup_complete=true`，检查 UUID 和持久回执后结束等待，拒收该解析的产物。 |
| `COMPLETED` | `0` | 本次解析先完成且成功回执有效。字段为 `accepted_exit=true`、`cleanup_complete=true`，`receipt=null`。继续按既有解析合同验收。 |
| `CANCEL_PENDING` | `3` | 取消意图已持久化，尚无已确认的终态。忽略已有解析产物，重试原 UUID 或轮询 `reconcile`。 |
| `CANCEL_ERROR` | `2` | UUID 无效或任务不存在。无效 UUID 的 `run_id` 为 `null`。 |
| `CANCEL_ERROR` | `1` | 部署控制失败。记录错误码，按原 UUID 恢复或由运维检查。 |

正常的 `cancel` 调用在 stdout 输出一个 JSON 对象。参数解析错误使用 `argparse` 的退出码 `2` 和 stderr。`reconcile` 在已有取消意图时返回同版取消状态，并沿用其查询退出语义。取消前的普通运行状态和已有成功完成回执保留原形状。协调失败时应按原 UUID 重试。`reconcile-all` 返回该次查询的状态列表并写入扫描状态。协调错误或取消回收错误使扫描失败。等待未确认提交的租约到期仍是可协调的状态。JudgeAI 应始终检查返回的 UUID 和状态。

| `error_code` | 含义与恢复 |
| --- | --- |
| `INVALID_JOB_ID`、`JOB_NOT_FOUND` | UUID 格式不合法，或当前登记目录中没有该 UUID。核对原始登记。 |
| `STATE_ROOT_INVALID`、`STATE_IO_ERROR` | 登记目录、平台、运行记录或持久化操作异常。核对环境和文件状态，必要时用原 UUID 重试。 |
| `JOB_OWNERSHIP_MISMATCH` | Manager 返回的标签对应其他 plist。控制器拒绝对该登记发送信号或卸载。 |
| `LAUNCHD_UNAVAILABLE`、`DEADLINE_EXCEEDED` | Manager 无法核验或调用预算用尽。Manager 不可用时，通常先持久化取消意图并返回 `CANCEL_PENDING`。若本地 Supervisor 已记录可能成功的结果，则返回 `CANCEL_ERROR`，由调用方在恢复后重试以优先核验完成状态。 |
| `SUBMISSION_UNCONFIRMED` | 发现提交意图，Manager 尚未给出可核验登记，租约未到期。按原 UUID 继续协调。 |
| `BOOTOUT_FAILED`、`SCOPE_STILL_REGISTERED` | 已观察到的 Manager 登记仍需回收。后续协调将再次核验 Job 归属。 |
| `INVALID_CLAIM`、`PROCESS_OBSERVATION_UNAVAILABLE`、`GROUP_NOT_EMPTY` | 进程组归属或空组尚未获得可验证证据。保持等待并检查环境，直到协调可验证清理。 |

成功取消时，`receipt` 包含 `requested_at`、`confirmed_at` 两个 Unix 时间戳和 `verification`。重复取消读取同一持久回执。

| `verification` | 回执依据 |
| --- | --- |
| `GROUP_EMPTY` | 已启动过受管 Job。核验 launchd 中该登记消失，并观察到其任务进程组为空。 |
| `NEVER_SUBMITTED` | UUID 尚无提交意图，未发现 Manager 登记，持久取消意图已使该 UUID 不能提交。 |
| `REGISTRATION_REVOKED` | 核验并撤销了已观察的 Manager 登记，Core 未进入已声明的任务范围。 |
| `LEASE_REVOKED` | 未确认的提交已过期，未发现 Manager 登记或 Core 启动声明。持久取消意图继续阻止迟到登记启动 Core，此回执未依赖 bootstrap 确认。 |

PID、PGID 与启动时间用于观测，控制命令只使用核验过的 Job 归属。PGID 复用可能暂时延迟空组确认。空组回执的边界是 macOS Job 的进程组。主动 `setsid()`、原生脱组、管理器故障以及超出进程组的工作仍需独立能力验证。
