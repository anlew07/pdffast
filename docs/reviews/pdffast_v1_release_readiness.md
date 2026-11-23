# PDFFast V1 发布准备审阅

审阅日期 2026-11-23（Asia/Shanghai）。

**结论：NOT_READY。** PR1～PR3 的修复后候选通过验证，可以提交评审。联合生产发布仍缺目标部署的强制退出进程树回收证据和已批准 clean Commit 的正式身份。历史基线失败须按发布审批规则处理。

## Git 与审阅范围

PDFFast 工作区为 `/Users/admin/Workspace/pdffast-v3`，分支 `main` 跟踪 `origin/main`，HEAD 为 `63eeff3721b9b3de2acdc4de7df75bc9e61477f6`。相对本地 `origin/main` 的 ahead / behind 为 0 / 0。审阅起点为 20 个已跟踪文件修改、13 个未跟踪文件和空暂存区。审阅交付后的工作区含同一批 20 个已跟踪修改和 14 个未跟踪文件（含本报告），暂存区为空。正式发布 Commit 待审批。JudgeAI 仅做只读对照，锁仍为 `WAITING_FOR_PDFFAST_RELEASE`。

| 路径范围 | 已审阅的原始 33 个文件 |
| --- | --- |
| API 与入口（5） | `pdffast/__init__.py`、`pdffast/errors.py`、`pdffast/parser.py`、`pdffast/application/parse_service.py`、`pdffast/preflight.py` |
| 配置身份（6） | `pdffast/application/production_identity.py`、`pdffast/application/production_preflight.py`、`pdffast/application/production_profile.py`、`pdffast/providers/profiles.py`、`pdffast/providers/registry.py`、`pdffast/providers/rapidocr.py` |
| 执行与来源（7） | `pdffast/fallback/executor.py`、`pdffast/fallback/policy.py`、`pdffast/pipeline/context.py`、`pdffast/pipeline/runner.py`、`pdffast/application/parser_provenance.py`、`pdffast/result.py`、`pdffast/providers/workers.py` |
| 验收脚本（4） | `scripts/run_indra_triple_regression.py`、`scripts/run_pipeline.py`、`scripts/verify_indra_runtime.py`、`scripts/verify_production_governance.py` |
| 回归测试（6） | `tests/contracts/test_frozen_configs.py`、`tests/unit/test_cli_log_output.py`、`tests/unit/test_provider_lifecycle.py`、`tests/unit/test_provider_profiles.py`、`tests/unit/test_parser_provenance.py`、`tests/unit/test_production_preflight.py` |
| 合同与原验收（5） | `docs/contracts/production_parser_identity_v1.md`、`docs/contracts/production_parser_identity.v1.schema.json`、`docs/contracts/parser_provenance_v1.md`、`docs/contracts/parser_provenance.v1.schema.json`、`docs/reviews/production_profile_governance_v1.md` |

## 七项全量失败归因

使用同一套现有 Python 3.12 依赖，在原候选和独立的 `git archive 63eeff3721b9b3de2acdc4de7df75bc9e61477f6` 快照中重跑 `tests/unit/test_phase4_core.py` 与 `tests/contracts/test_production_import_boundaries.py`。两边都是 7 failed、2 passed，首个失败原因逐项一致。原候选全量复跑为 601 passed、7 failed、23 skipped。

历史基准路径为 `/Users/admin/Workspace/pdffast/outputs/pipeline_runs/case_008_final_bench_v1`。Stage 6 指 `06_stage6/normalized_text_flow.json`，Stage 10 指 `10_1_canonical/canonical_document.json`。

| 测试 | 失败原因 | 旧基线复现 | 本次引入 | 发布影响 | 结论 |
| --- | --- | --- | --- | --- | --- |
| `test_canonical_builder_matches_reference_artifact_shape` | 缺 Stage 6 文件 | 是 | 否 | 历史 Canonical 对照待补 | BLOCKED |
| `test_renderer_is_pure_and_matches_reference_markdown` | 缺 Stage 10 文件 | 是 | 否 | 历史 Markdown 对照待补 | BLOCKED |
| `test_renderer_does_not_invent_heading_for_unresolved_section` | 缺 Stage 10 文件 | 是 | 否 | 历史标题对照待补 | BLOCKED |
| `test_structure_audit_passes_on_reference_artifacts` | 缺 Stage 6 文件 | 是 | 否 | 历史 Audit 对照待补 | BLOCKED |
| `test_stage10_core_works_when_installed_outside_legacy_workspace` | 缺 Stage 6 文件 | 是 | 否 | 历史样例的安装态对照待补 | BLOCKED |
| `test_stage10_runner_writes_only_declared_artifacts` | 缺 Stage 6 文件 | 是 | 否 | 历史样例的产物白名单对照待补 | BLOCKED |
| `test_core_package_does_not_import_service_frameworks_or_http_types` | MiniCPM 的 `urllib.request.Request` 触发既有 AST 断言 | 是 | 否 | 影响全量零失败门槛，V1 三模型 Profile 无 MiniCPM 运行路径 | BASELINE_FAILURE |

历史测试与断言保持原样。取得原始基准后应复跑六项对照。仓库若允许带已知基线问题发布，需要明确记录适用范围和审批。以上七项均无 V1 回归证据。

## 跨仓库合同与可复现性

两份文档和两份 Draft 2020-12 Schema 使用字符串 `"1.0"`。Schema 约束结构，源码和消费端共同完成跨字段验证。

| 字段 | V1 规则 |
| --- | --- |
| `pdffast_commit` | 已加载 PDFFast 源码所在 Git checkout 的 HEAD，40 或 64 位小写十六进制，须与 `code_identity.pdffast_commit` 相等。没有 Git 元数据时为 `null`。JudgeAI 当前部署 pin 使用已批准的 40 位 Commit。 |
| `code_identity`、`source_dirty` | Git Checkout 返回布尔 dirty，盘上 PDFFast Python 源文件按相对 POSIX 路径映射到文件 SHA-256，再规范化为源码总 SHA。算法 SHA 用对应源码子集。Git 状态范围为源码、配置与项目锁文件，JudgeAI 另验整棵工作树干净。无 Git 元数据时 dirty 为 `null`。 |
| `profile_sha256`、`providers_config_sha256` | 实际加载原始字节的 SHA-256，64 位小写。显式根目录与包内资源各用自己的配置，路径用作诊断。 |
| `effective_config_fingerprint` | PDFFast 对规范化 `fingerprint_input` 计算 SHA-256。覆盖原始配置、冻结路由、候选顺序、适配器与 normalizer、语义参数、代码身份、模型与运行时身份、核心依赖、主机和语义环境。预检失败时为 `null` 或缺省。JudgeAI 消费返回值。 |
| `allowed_providers`、`capability_routes` | 名单和所有候选链均为有序、唯一的非空名称数组。四条路线须完整，链内 Provider 属于已批准名单。预检和解析逐项比对，顺序有语义。 |
| `attempted_provider_counts`、`selected_provider_counts` | Provider 到正整数的映射，零任务用空对象。实际进入执行计尝试，真实接受的唯一结果计选中。按执行计划、派发批次、索引、任务记录和汇总互证。选中总数等于接受数，三类结果总和等于任务总数。 |
| `execution_status` | `COMPLETED` 或 `COMPLETED_WITH_PIPELINE_FAILURES`。后者为诊断产物。JudgeAI 要求前者、零失败、Audit 通过和实际退出码 0。配置、环境、执行、输出异常沿独立失败路径传播。 |

相同源码字节可在提交前后得到相同 `source_sha256`。新 HEAD 进入指纹输入，因而批准的新 Commit 会产生新有效指纹。单独改变 dirty 标签不会改变指纹。源码字节变化会改变源码 SHA。发布 pin 还会随真实运行时、路径、语义环境或模型身份变化。安装包的 null Git 身份有明确定义，当前 JudgeAI 发布锁要求可验证的干净 Git checkout。

Core 预检和当次解析共用代码路径与锁定快照。外部预检和解析内部预检分别执行，JudgeAI 用 pin 及最终 provenance 交叉核验。Profile、Provider 配置、路由、适配器及已捕获的 Worker 环境统一消费。已验证运行时资产应在部署期间保持不可变，尤其是声明级模型文件、解释器与第三方包。

本次修复保持 V1 wire 字段、类型和错误状态兼容。正式发布前的候选指纹会变化，且原 API 的显式生产 Profile 调用现在需要完整严格配置与独占 run ID。默认无 Profile 的路径保留历史路由与结果格式。验收脚本的批处理控制台日志现位于批次目录，报告索引给出实际路径。

## 代码审阅发现

| 严重度 | 发现与影响 | 处理与证据 |
| --- | --- | --- |
| BLOCKER | Core 被直接强杀或 native abort 时，已单独建会话的 Worker 可能留存。JudgeAI 当前只向 Core 和它的进程组发信号，`pdffast_embedded_adapter.py:212–229`，覆盖不到新的 Worker 会话。 | 尚待目标部署门禁。为单次解析建立可覆盖全部后代的进程监管范围，并验证 Core 强杀、native abort 和超时后无后代残留。生产结果继续拒收非零退出。 |
| HIGH | 锁定 Worker 的响应超时、非 JSON 或非对象响应曾清理进程后走普通尝试失败分支，可能被合法回退掩盖。 | 已修复。`pdffast/providers/workers.py` 统一把锁定模式的协议与传输故障传播为 `WorkerShutdownError`。真实子进程负向回归覆盖了三个路径。 |
| HIGH | 预检读取的环境可能与 Worker 启动时读取的环境不同，二次展开可改变模型配置，而来源沿用预检指纹。 | 已修复。`production_profile.py` 捕获环境，路径展开、依赖检查和锁定 Worker 共用它。Core 在开始与发布前检测约定语义环境漂移。覆盖预检后漂移和发布前漂移。 |
| HIGH | 继承 `GIT_DIR`、`GIT_WORK_TREE` 等变量可使源码 SHA 与其他仓库的 Commit 混合。实际复现了 PDFFast 源码携带 JudgeAI HEAD 和 `source_dirty=false`。 | 已修复。`production_identity.py` 清除继承的 Git 上下文并核对实际工作树根。回归还确认 dirty 标记本身和 HEAD 变化的不同影响。 |
| HIGH | Core 能处理 SIGTERM 时，旧 Worker 仍可能占完 JudgeAI 的 5 秒宽限期。真实合成子进程复现中，Core 退出码为 `-9`，Worker 仍活着。 | 已修复协作取消。`workers.py` 在锁定取消路径直接回收所属会话和已识别后代。复测 Core 在约 0.13 秒走取消退出，Worker PID 已消失。直接强杀仍受上方发布门禁约束。 |
| HIGH | 环境漂移修复首轮在真实 `case_001` 和 `case_003` 发现误拒绝。OpenCV 导入会在进程内更新仅供后续子进程使用的 `LD_LIBRARY_PATH`。 | 已修复。保留启动值进入指纹和 Worker 快照，Core 运行中漂移检查排除这一项，其他约定环境变量仍受检查。新增回归验证误拒绝消失及 Worker 接收原值。 |
| MEDIUM | 独立验收曾在缺少 run ID、输入 SHA 和 Stage 9/最终计数一致性验证时返回 PASS。 | 已修复。`scripts/verify_production_governance.py` 将验收与输入、运行和产物重新绑定，独立对照任务账目，并核对隔离 Provider 的预检指纹。伪成功回归已通过。 |
| MEDIUM | 候选将严格 BYE/退出码异常扩展到历史无 Profile Worker，可能改变既有调用的关闭语义。 | 已限定在锁定模式。锁定和默认模式均测试了 BYE 后退出 0、7 和 -6，历史模式继续按原语义关闭。 |
| MEDIUM | Indra、MinerU 的 V1 身份级别为 `DECLARED_AND_PRESENT`。依赖清单标识包名与版本，无法证明同版本二进制、模型字节、驱动或重复发行包的实际选择完全相同。 | 发布环境须固定镜像、只读模型和解释器树，验证发行包来源与唯一性。Indra 可执行已存在的逐文件校验，MinerU 应用获批模型清单。RapidOCR 当次预检校验固定 ONNX 字节。 |
| MEDIUM | 锁定 manifest 的 PDF SHA 是解析前观测值。解析会在多个阶段打开文件。一次前后都恢复原字节的外部修改可能越过观察。 | 直接调用依赖稳定的输入路径和文件。JudgeAI 和验收工具核对输入观测值，发布时用不可变输入存储。 |
| MEDIUM | 现有 `fallback-crop-contract.yml`、`indra-contract.yml` 未覆盖全部治理测试。 | 发布审批须记录本报告对应的治理回归与真实验收。CI 门禁接入可独立安排。 |
| MEDIUM | 历史 MiniCPM 导入断言违反 Core 既有边界，且六个历史结构测试无参考产物。 | 逐项在旧基线复现，详见归因表。发布审批须处理全量零失败门槛。 |
| LOW | Core 进度日志的 `parse_finished` 可早于最终原子发布或最终环境校验异常。 | 使用最终 manifest、V1 状态及子进程退出码判定可接受结果。 |
| LOW | 批量验收的控制台日志从 case 子目录移至批次目录。 | 批次索引已经输出新路径。按旧固定路径找日志的调用方应改用索引。 |
| LOW | 语义环境守卫检查入口和发布时的约定前缀，兼容已有进程 API 和诊断变量。 | 发布使用新解释器与固定进程环境。短暂修改再恢复、未声明的第三方影响由部署隔离约束。 |

支持入口的闭包检查覆盖 API、Core 与 CLI。Profile 是允许名单与有序路线来源。显式 registry、Provider 配置注入、插件、normalizer 和路线 override 被拒绝。Provider 适配器绑定须与发布实现匹配，严格运行时检查只为三类生产适配器生成 READY。内部测试和低层执行器仍支持依赖注入，生产接入走受保护的公开入口。

来源交叉校验使用实际任务调用。零任务仍执行 Native、Canonical、Markdown 和 Audit。合法回退和终止保留的成功条件未变化。最终 manifest 在 Provider 清理、来源校验、产物写出和 Audit 之后原子替换。当次最终提交点之后的非零父进程退出仍由消费者拒绝。原子替换提供文件发布边界。断电持久性由部署文件系统保障。

## 最终验证

| 工作包 | 修复后结论 | 验证 |
| --- | --- | --- |
| PR1 配置闭包 | PASS | Profile、冻结配置、四条路线、注入拒绝、适配器绑定与真实回退通过。 |
| PR2 预检与配置身份 | PASS（候选） | 同一运行时的普通预检和 `--probe` 在两个新进程中得到相同指纹。三个 Provider 均 READY 且探测为 PASS。两份报告通过 Draft 2020-12 校验。错误 Profile 返回 `CONFIGURATION_FAILED`、退出码 2。Indra 已额外通过逐文件 SHA 校验。 |
| PR3 解析来源 | PASS（候选） | 五份真实 PDF、两页 Native-only 和三个隔离 Provider 全部退出 0。六份最终来源均通过 Draft 2020-12 和 JudgeAI 强类型验证。重新核对 PDF SHA、run ID、Canonical 页数、Markdown、Audit 及来源身份。 |
| PR4 原生崩溃 | REPRODUCED / BLOCKED | 合并前 macOS 实测复现 MinerU BYE 后以 SIGABRT 退出。崩溃报告将 `recursive_mutex lock failed` 定位到 ONNX Runtime 的 Events 线程，触发条件尚未确定。临时 Job 回收通过，失败回执拒绝该运行。详见 [Worker 归属复核](pdffast_v1_deployment_recovery.md#2026-11-23-合并前-worker-归属复核)。 |

- 最终定向回归 **168 passed、1 skipped**，跳过项缺参考仓库配置。Worker 生命周期文件 **36 passed**，已包含在定向回归中。
- 最终全量复跑 **615 passed、7 failed、23 skipped**。七项与旧基线逐项一致。 `git diff --check` 通过。
- 五份真实 PDF 共 246 页、172 个规划任务、186 次实际尝试、167 个接受、5 个合法终止保留、0 个流水线失败、0 次名单外调用。所有最终报告显示 `source_dirty=true`。证据目录为 `/tmp/pdffast-v1-readiness.MX9GQ7YE`。
- 本机报告是修复后重新生成的候选证据。正式部署须在获批 Commit 与最终路径上重生成两份预检，重跑实际验收。

| 真实样例 | 页数 | 规划 | 接受 | 终止保留 | OS 退出码 / Audit |
| --- | ---: | ---: | ---: | ---: | --- |
| case_001 | 30 | 19 | 16 | 3 | 0 / PASS |
| case_002 | 16 | 1 | 1 | 0 | 0 / PASS |
| case_003 | 66 | 54 | 52 | 2 | 0 / PASS |
| case_004 | 114 | 92 | 92 | 0 | 0 / PASS |
| case_005 | 20 | 6 | 6 | 0 | 0 / PASS |
| Native-only | 2 | 0 | 0 | 0 | 0 / PASS |

## 发布审批与 JudgeAI 接线

1. 从当前基线和审阅后的工作区准备独立评审分支，建议 `release/pdffast-production-governance-v1`。正式提交由获授权的维护者完成。提交内容应包含实现、对应回归、两份文档和两份 Schema。Review 后由维护者批准准确的 40 位 Commit。
2. 在目标部署环境，以最终路径、现有 Python 3.12 和锁定依赖准备该 Commit 的干净 checkout。取得获批的模型清单，验证物理文件与运行时来源。以新解释器分别生成普通预检和依赖探测报告，确认两个指纹一致且 source dirty 为 false。
3. 运行治理回归、两份 Schema、Native-only、三个隔离 Provider、五份真实 PDF 及目标进程监管验证。参考缺失和旧导入断言应按审批政策恢复验证或取得明确例外。驱动或锁定依赖发生变化时，重新取得批准的身份与 PDF 证据。
4. JudgeAI 协议适配无需调整。联合部署还须证明强杀后的跨会话回收。Linux 可使用单次运行独占的 cgroup，macOS 需等效的进程树监督。应使用真实启动方式注入直接 SIGKILL、SIGABRT、超时和取消，确认所有已知后代退出、未影响并发的独立运行，并确认有产物的非零退出也被拒收。
5. 在已准备好的 JudgeAI 目标运行目录通过 `pdffast_version.py update --prepared` 录入获批报告，再运行版本检查、原生验收及隔离 worker 联验。Profile path 和 SHA、源码 SHA、Provider 配置 SHA、两份 Schema 版本及指纹取自目标部署的实际报告。候选 JSON 继续作为测试证据。未具备正式身份和异常回收门禁时保持 `WAITING_FOR_PDFFAST_RELEASE`。

### 可复制的 PDFFast 发布验收命令

在最终部署 checkout 根目录运行。准备已批准的 `APPROVED_SHA`、样例目录 `PDF_ROOT` 和 checkout 外尚不存在的绝对输出目录 `EVIDENCE_ROOT`。模型与校验环境应已按上面的发布步骤就绪。

```bash
(
  set -eu
  : "${APPROVED_SHA:?}" "${PDF_ROOT:?}" "${EVIDENCE_ROOT:?}"
  test "$(git rev-parse HEAD)" = "$APPROVED_SHA"
  test -z "$(git status --porcelain)"
  profile="configs/profiles/production.indra-triple.json"
  core="$PWD/.venv/bin/python"
  export PYTHONDONTWRITEBYTECODE=1
  mkdir "$EVIDENCE_ROOT"

  "$core" -B scripts/verify_indra_runtime.py --hashes
  "$core" -B -m pdffast.preflight --project-root "$PWD" \
    --provider-profile "$profile" --probe --json > "$EVIDENCE_ROOT/preflight_probe.json"
  "$core" -B -m pdffast.preflight --project-root "$PWD" \
    --provider-profile "$profile" --json > "$EVIDENCE_ROOT/preflight_default.json"

  "$core" -B - "$EVIDENCE_ROOT" "$APPROVED_SHA" <<'PY'
import json
import sys
from pathlib import Path
from pdffast.application.production_identity import fingerprint

evidence = Path(sys.argv[1])
probe = json.loads((evidence / "preflight_probe.json").read_bytes())
default = json.loads((evidence / "preflight_default.json").read_bytes())
for report in (probe, default):
    assert report["schema_version"] == "1.0" and report["status"] == "PASS"
    assert report["pdffast_commit"] == report["code_identity"]["pdffast_commit"] == sys.argv[2]
    assert report["code_identity"]["source_dirty"] is False
    assert report["effective_config_fingerprint"] == fingerprint(report["fingerprint_input"])
assert probe["effective_config_fingerprint"] == default["effective_config_fingerprint"]
assert all(p["status"] == "READY" and p["dependency_probe"] == "PASS"
           for p in probe["provider_runtime"].values())
PY

  verify_run() {
    run_id="$1"
    shift
    "$core" -B -m scripts.verify_production_governance --project-root "$PWD" \
      --provider-profile "$profile" --output-root "$EVIDENCE_ROOT" \
      --run-id "$run_id" "$@" > "$EVIDENCE_ROOT/$run_id.json"
  }

  verify_run native-only --native-only
  for case_id in case_001 case_002 case_003 case_004 case_005; do
    verify_run "$case_id" --pdf "$PDF_ROOT/$case_id.pdf"
  done
  for provider in $("$core" -B -c \
      'import json, sys; print(*json.load(open(sys.argv[1]))["allowed_providers"])' \
      "$EVIDENCE_ROOT/preflight_probe.json"); do
    verify_run "isolated-$provider" --provider "$provider"
  done

  "$core" -B -m pytest -q -p no:cacheprovider \
    tests/contracts/test_frozen_configs.py tests/unit/test_provider_profiles.py \
    tests/unit/test_production_preflight.py tests/unit/test_parser_provenance.py \
    tests/unit/test_provider_lifecycle.py tests/unit/test_native_only_provider_plan.py \
    tests/unit/test_fallback_executor.py tests/unit/test_cli_log_output.py
  git diff --check
)
```

使用已有 `jsonschema` 的验证解释器，将 `SCHEMA_PYTHON` 指向该解释器。该验证只读 Schema 和验收 JSON，可与 OCR 运行环境隔离。

```bash
"$SCHEMA_PYTHON" -B - "$EVIDENCE_ROOT" <<'PY'
import json
import sys
from pathlib import Path
from jsonschema import Draft202012Validator

root = Path(sys.argv[1])
schema_dir = Path("docs/contracts")
identity = Draft202012Validator(json.loads(
    (schema_dir / "production_parser_identity.v1.schema.json").read_bytes()))
provenance = Draft202012Validator(json.loads(
    (schema_dir / "parser_provenance.v1.schema.json").read_bytes()))
for name in ("preflight_probe", "preflight_default"):
    identity.validate(json.loads((root / f"{name}.json").read_bytes()))
for run in ("native-only", "case_001", "case_002", "case_003", "case_004", "case_005"):
    result = json.loads((root / f"{run}.json").read_bytes())
    manifest = json.loads((root / run / "result/manifest.json").read_bytes())
    assert result["returncode"] == 0 and result["acceptance"] == "PASS"
    provenance.validate(manifest["parser_provenance"])
PY
```

全量套件应另行执行并保留退出码与完整日志。上文列出的七个基线失败需由发布审批处理。

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q --tb=short -p no:cacheprovider
```

联合部署通过异常回收门禁后，在已准备好目标运行目录的 JudgeAI 根目录执行。预检文件须来自 JudgeAI 即将使用的 `.runtime/pdffast` 本身。该操作发布 JudgeAI 锁，需另行批准。

```bash
profile='configs/profiles/production.indra-triple.json'
identity="$EVIDENCE_ROOT/preflight_probe.json"
profile_sha="$(.venv/bin/python -B -c \
  'import json,sys; print(json.load(open(sys.argv[1]))["profile_sha256"])' "$identity")" &&
.venv/bin/python scripts/pdffast_version.py update "$APPROVED_SHA" --prepared \
  --profile "$profile" --profile-sha256 "$profile_sha" --identity "$identity" &&
.venv/bin/python scripts/pdffast_version.py check &&
.venv/bin/python scripts/verify_pdffast_native.py
```


## 2026-11-23 两项 P0 最终验收

| 判断 | 结果 | 最终证据 |
| --- | --- | --- |
| `MINERU_SHUTDOWN_STABILITY` | PASS | Macintosh MinerU 3.4.5 / ONNX Runtime 1.30.0 的原生遥测回调 SIGABRT 已定位。macOS MinerU 在子进程启动前禁用遥测后，30/30 独立真实推理并自然退出 0。导入后 API 组复现 1/16，默认对照本轮 0/40。见 [MinerU P0-A 验收](pdffast_v1_mineru_shutdown.md)。 |
| `DEPLOYMENT_HEALTH_CONTRACT` | PASS | 最终公开 CLI 在缺近期扫描时 `BLOCKED`，完成扫描并实测独立 Job 的 SIGKILL 回收后 `PASS`。同时验证身份不匹配、过期与失败扫描。 |
| `JOB_CANCEL_CONTRACT` | PASS | 最终定向回归的协作、暂停 Supervisor 后重启控制器回收分别为 0.2924 秒和 4.1096 秒。真实 `case_001` 在 MinerU PDF 渲染器存活时执行 CLI cancel，0.200 秒返回 `GROUP_EMPTY`，重复调用回执一致。 |
| `PDFFAST_CODE_MERGE_READY` | YES | 最终定向回归 149 项通过，其中真实 launchd 部署集 19 项。 |

最终源码通过受管 `case_001`（30 页、19 个规划任务）及 Native-only（2 页、0 个规划任务）。Audit、两份解析 Schema、成功回执和空组均通过。Health 和 PDF 预检的源码身份相同。两份部署控制 Schema 已用实际 JSON 响应验证。`git diff --check` 通过，Ruff 无新增诊断，原 42 项基线诊断保留。

[JudgeAI 部署控制接线](../contracts/deployment_control_v1.md)描述 JSON 格式、退出码、重试语义和五秒预算。代码合并门禁按本机验收关闭。正式发布仍需目标环境、定时扫描配置、获批发布锁及 JudgeAI 端到端验收。macOS 进程组无法覆盖主动脱组的工作。未安装依赖，未提交或修改 JudgeAI。

最终 PDF、CLI 和定向回归证据分别在 `/private/tmp/pdffast-p0-mineru.Yn2QH0Uw/closed-source-pdf`、`closed-source-control`、`real-cancel` 和 `closed-source-targets.log`。
