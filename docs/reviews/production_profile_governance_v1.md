# JudgeAI × PDFFast 生产解析配置治理 V1 验收

日期为 2026-11-20（Asia/Shanghai）。工作目录为 `/Users/admin/Workspace/pdffast-v3`。

## 基线

当前分支 `main`。本地 HEAD 和 JudgeAI 参考均为 `63eeff3721b9b3de2acdc4de7df75bc9e61477f6`，本地相对参考 Ahead / Behind 为 0 / 0。任务开始时已跟踪与未跟踪工作区为空，无前置修改冲突。当前有本任务的未提交解析源码、测试和文档，预检记录 `source_dirty=true`。HEAD 只标识基线。

| 候选身份 | 值 |
| --- | --- |
| Profile SHA-256 | `12446eefdfdc92dafc861c3c0fb8f76eb342b48b6e7659e40110927886d40971` |
| 实际使用的根目录 providers.json SHA-256 | `99c895dfef4016424621e8d614e27cb215b02ac78be114ce62de0e38a8e13dc3` |
| 打包 providers.json SHA-256 | `9de971e198a849713fcc18db28142140f3a84b184cc3f608440bd14bc4b323da` |
| 源码 SHA-256 | `130faa9911d9abe71717ed51ad13c76e82cc6920068d269b85174d735ed4f72e` |
| 有效配置指纹 | `068d2bd00d78d18d422ad99f6820a7c7e48d72ac1de207c3294bd990a65480ed` |
| 身份 / 来源 Schema | `"1.0"` / `"1.0"` |

## 源码审阅

位置为当前工作树中的函数，原有能力基于任务开始时读取的基线。状态描述基线。

| 文件及位置 | 函数 | 当前基线行为与原有能力 | 状态与缺口 | 修改结果 |
| --- | --- | --- | --- | --- |
| `pdffast/parser.py:31`、`pdffast/config.py:13` | `PDFFastParser.parse`、`ParserConfig` | Facade 创建 Core 配置，`ParserConfig` 校验 DPI、模式等 | RISK。已有 config 时 facade Profile 被忽略 | 锁定设置来自同一入口，混用直接报配置错误 |
| `pdffast/application/parse_service.py:28`、`:44`、`:66` | `parse`、`_parse_locked`、`_parse` | 基线先写输入 metadata manifest，加载根目录或包内配置，再套用 Profile | NEEDS_CHANGE。相对 Profile 路径取当前目录，显式 Profile 可搭配注册器、配置等注入 | 统一锁定入口，根目录相对路径解析，校验完成后独占运行目录。历史默认路径保持兼容 |
| `pdffast/providers/profiles.py:35`、`:57` | `load_provider_profile`、`apply_production_profile` | 原有严格四路线、唯一名称、显式启用、链完整和使用覆盖 | PARTIALLY_IMPLEMENTED。JSON 重复键、不可用或错误实现的已启用 Provider 需检查 | 严格 JSON，新增 `production_profile.load_production_profile` 校验原始启用状态、适配器/插件绑定及快照 |
| `pdffast/providers/registry.py:88`、`:158`、`:183`、`:305` | `validate_runtime_provider_closure`、`supports`、`_prepare_config`、`create` | 运行闭包枚举完整候选。注册支持名称、kind、插件和自定义 factory。创建前准备本地路径、文件与声明 SHA | PARTIALLY_IMPLEMENTED。通用闭包接受自定义 registry，无法证明顺序与具体生产路线一致 | 锁定模式使用内部注册器，完整计划必须逐名逐序匹配。Indra 由正式插件绑定 |
| `pdffast/providers/base.py:10`、`indra.py:119`、`rapidocr.py:24`、`mineru.py:14` | `Provider`、各适配器生命周期 | 两个隔离 worker 与进程内 RapidOCR 执行。RapidOCR 基线将 params 交给引擎 | RISK。RapidOCR 原有文件 SHA 检查与引擎选用文件未绑定 | 锁定模式为 Det/Rec/Cls 注入经校验的本地路径和 ONNX Runtime 引擎 |
| `pdffast/fallback/planner.py:335`、`router.py:298` | `create_fallback_plan`、`create_capability_plan` | 从 Quality 生成任务与四条能力路由，并可处理合法零任务 | ALREADY_IMPLEMENTED。可直接沿用 | 保留质量判断、任务生成和渲染语义 |
| `pdffast/fallback/policy.py:656`、`:782` | `apply_provider_chain_overrides`、`create_provider_execution_plan` | 能全量覆盖历史候选链，保留接受及终止策略 | PARTIALLY_IMPLEMENTED。候选文件基线在执行计划生成时重新打开 | 锁定规划消费预检过的冻结候选快照 |
| `pdffast/fallback/executor.py:85` | `execute_provider_plan` | 按 wave 初始化、派发、回退和清理，生成 attempts、selection 和旧汇总 | PARTIALLY_IMPLEMENTED。原有闭包验证注册与启用，对返回结果身份和 Profile 路线缺乏精确约束 | 执行前逐序校验，隔离计划与任务元数据，校验 raw/normalized 身份。清理异常继续阻止最终结果 |
| `pdffast/pipeline/runner.py:44`、`:166`、`pipeline/context.py:14`、`pipeline/artifacts.py:81` | `run_stage10`、`run_core_pipeline`、`PipelineContext`、`ArtifactPaths` | Stage 9 清理后返回 selection，Stage 10 构建、渲染、Audit 及写文件。Audit 基线返回状态对象 | RISK。锁定场景需保证 Audit 通过和清理结束后再发布 | 交叉校验结构化执行证据，锁定 Audit 失败抛错，最终 manifest 原子发布 |
| `pdffast/result.py:13`、`render/llm_ready.py:25`、`audit/structure_boundary.py:21` | `ParseResult.from_pipeline`、`build_rendered_document`、`audit` | 公开结果兼容历史 mapping，Renderer 和 Audit 使用内置实现 | MISSING。缺少可机读产物来源 | 增加 Python 属性和最终对象，保留旧 mapping 与结构语义 |
| `pdffast/providers/workers.py`、`pdffast/runtime.py:303` | `JsonLineWorker.preflight`、`_terminate`、`close`、`observe_parse` | 依赖探测独立执行。worker 有断开、terminate/wait、子进程归属和 heartbeat 清理机制 | RISK。基线对 BYE 后的 `wait()` 不检查返回码。历史 C++ 崩溃原始堆栈缺失，根因 BLOCKED | BYE 后必须观察到退出码 0。异常退出不能经重启掩盖。锁定探测和执行使用隔离解释器参数。原始崩溃在当前候选未复现 |
| `pdffast/service/app.py:143`、`:294`、`service/__main__.py:12` | `create_parser`、`parse_pdf`、`build_config` | HTTP 请求上传文件，服务端默认构造 parser，启动器没有 Profile pin，响应含 Markdown、Canonical、Audit | MISSING。HTTP 未提供 V1 预检、锁定或来源输出。没有任意 Profile 请求参数 | 保持 HTTP 兼容。V1 接入使用独立 Core 子进程 |

## 独立评审

独立评审触发七项负向回归。修正了隔离 worker 从工作目录导入模块、异常退出后静默重启、Indra 自动选择未声明的顶层权重、RapidOCR 参数环境插值、非法 Profile 路径未分类、旧默认模式可能复用锁定目录、最终写入期间的取消。当前模型文件与环境的额外风险见身份合同中的已声明模型验证级别。

## 四个工作包

- PR1 PASS。配置加载、四链闭包、原始模式区分、注入防护与实际结果身份守卫通过定向回归。测试含不存在、非法/重复 JSON、冲突、未经允许候选与合法回退。
- PR2 PASS。独立 Python API 与 CLI 通过。CLI 坏路径输出结构化失败且退出 2。同配置跨进程身份一致，源码 digest 区分 dirty 快照。三模型都 READY，`--probe` 均通过。Indra 1.1.2 revision `bd02167fdf2005a19962cc15188f8496a2c87d3b` 与 MinerU 3.4.5 revision `ed6b654c018d742e65a17671e379c5e6ecc87ec9` 声明且文件存在。RapidOCR 3.9.2 使用 ONNX Runtime 1.30.0，三个 ONNX SHA 实际验证。
- PR3 PASS。实际非零任务与 Native-only 均生成可验证来源。两份 Draft 2020-12 Schema 使用现有环境的 jsonschema 验证。最终产物与中间文件分界、Audit 失败和原子发布通过回归。
- PR4 BLOCKED。故障注入成功复现旧代码吞掉 BYE 后退出 7 和 -6 的缺口，修正后的测试区分这三类退出。Core 父进程测试还注入了产物写完后 SIGABRT。真实隔离推理、两页 Native-only 和五份真实 PDF 均退出 0。历史 `recursive_mutex lock failed` 为 NOT_REPRODUCED，来源于哪个 C++ 库或进程退出阶段仍待原始 crash report/call stack。故障注入没有证明历史 native 崩溃已解决。

## 自动化测试

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q --tb=short -p no:cacheprovider
git diff --check
```

定向回归为 170 passed、0 failed、1 skipped，覆盖配置冻结、四工作包、原有默认解析和脚本兼容。全仓库 pytest 为 601 passed、7 failed、23 skipped。六项 Phase 4 回归因旧夹具缺失而 BLOCKED。缺失根目录为 `/Users/admin/Workspace/pdffast/outputs/pipeline_runs/case_008_final_bench_v1`。另一项为基线 MiniCPM 导入 `urllib.request.Request` 命中既有 Core 导入断言。与本任务相关的冻结配置测试现分别校验实际根目录、打包资源、生产 Profile 及冻结路由，并单独固定 Indra 插件身份。Skipped 包含缺少 `fitz`、参考仓库或样例参数。

## 真实 PDF 验收

以下数据来自当前候选 SHA。每行均有有效 Markdown、Canonical、最终 manifest，`execution_status=COMPLETED`。末列依次为结构 Audit、独立 subprocess.returncode、名单外调用数。

| PDF | PDF SHA-256 | 页 | 规划任务 | 实际尝试 | 实际选中 | Audit / 退出码 / 名单外 |
| --- | --- | ---: | ---: | --- | --- | --- |
| case_001 | `2e5df92403daf3c1ba164dc2fcfd289e602676b78dfe3e6486230d97292b8862` | 30 | 19 | Indra 18 / MinerU 5 / RapidOCR 6 | Indra 12 / MinerU 1 / RapidOCR 3 | PASS / 0 / 0 |
| case_002 | `f93885a1b52ab66c70b9bbb4068e59c13d1d4750d2113fdceae59a9158010da7` | 16 | 1 | Indra 1 | Indra 1 | PASS / 0 / 0 |
| case_003 | `4769d5180d5e54f8e0d7bbac81f01bcb184dd428adbd2aac4bc20007c755328c` | 66 | 54 | Indra 47 / MinerU 9 / RapidOCR 2 | Indra 45 / MinerU 7 | PASS / 0 / 0 |
| case_004 | `323b48f7293e0a8ff8d4378df64dea5da7bb3219966619d4734dee3965ac3cf4` | 114 | 92 | Indra 92 | Indra 92 | PASS / 0 / 0 |
| case_005 | `97eddae80a997f85b2f32e421a3548732ccd5555f231b7b6000b5afdad87ddf7` | 20 | 6 | Indra 6 | Indra 6 | PASS / 0 / 0 |

五份共 246 页，172 个任务，186 次实际尝试，167 个已接受任务，5 个合法终止保留，0 个流水线失败。case_001 和 case_003 覆盖 PAGE OCR、PAGE Layout、REGION、INLINE 及多 Provider 回退。case_001 三个 Provider 都真实产生了选中结果。结构复核发现五份的 Canonical 页数、PDF 页数和 manifest 输入哈希一致，Markdown 非空，Audit 的 `changed_stage6_base_record_count` 均为 0。逐字人工 OCR 对照为 NOT_RUN。

本地验收目录 `outputs/governance_v1_20261120/reviewed` 保存 `real_pdf_acceptance.jsonl`、`isolated_acceptance.jsonl`、`preflight_verified.json` 和各份产物。汇总仅含标识与结构化计数。此前验收候选和诊断产物保留。

### 独立复现命令

```bash
.venv/bin/python -m scripts.verify_production_governance \
  --project-root "$PWD" \
  --provider-profile configs/profiles/production.indra-triple.json \
  --output-root "$PWD/outputs/governance-repro" \
  --native-only
```

无模式参数时脚本会提示用法。把末行替换为 `--provider <由预检允许的 Provider 名>` 可运行隔离推理，替换为 `--pdf /absolute/path/to/existing.pdf` 可跑真实 PDF。父进程报告 returncode、脱敏阶段事件和 native mutex 诊断签名。

## 修改文件

| 文件 | 修改 |
| --- | --- |
| `pdffast/parser.py` | 拒绝拆散到 facade 与 config 的锁定设置 |
| `pdffast/application/parse_service.py` | 统一 Core 加载与预检，建立锁定目录所有权 |
| `pdffast/application/production_profile.py` | 解析可信 Profile、Provider 配置和冻结候选快照，限制适配器绑定 |
| `pdffast/providers/profiles.py` | 严格解码配置 JSON |
| `pdffast/providers/registry.py` | 执行链逐路由验证 |
| `pdffast/fallback/policy.py` | 规划复用冻结候选快照 |
| `pdffast/fallback/executor.py` | 守卫每个候选和实际结果身份，传播异常 worker 退出 |
| `pdffast/application/production_identity.py` | 计算规范化配置和源码身份 |
| `pdffast/application/production_preflight.py` | 检查运行时、模型、依赖导入位置和可选依赖探测 |
| `pdffast/preflight.py`、`pdffast/__init__.py` | 提供 CLI 与稳定 Core 导出 |
| `pdffast/providers/rapidocr.py` | 将已验 SHA 的本地权重交给实际运行引擎 |
| `pdffast/application/parser_provenance.py` | 交叉校验计划、派发、attempt 和 selected，原子发布 |
| `pdffast/pipeline/context.py`、`pdffast/pipeline/runner.py` | 传递锁定发布策略，在 Audit 与清理后提交最终 manifest |
| `pdffast/result.py`、`pdffast/errors.py` | 兼容扩展 provenance 属性与公共异常状态 |
| `pdffast/providers/workers.py` | 验证关停退出码，锁定导入环境与意外退出传播 |
| `scripts/run_pipeline.py` | 锁定模式使用 Core 权威配置，打印一致的流程与退出状态 |
| `scripts/run_indra_triple_regression.py`、`scripts/verify_indra_runtime.py` | 调整脚本日志落点以支持锁定目录独占 |
| `scripts/verify_production_governance.py` | 独立验收 Native、Provider 与真实 PDF，输出脱敏阶段和退出证据 |
| `tests/contracts/test_frozen_configs.py` | 分别验证根目录、打包资源和 Profile 的固定 SHA 与注册范围 |
| `tests/unit/test_provider_profiles.py`、`test_production_preflight.py` | 配置、锁定候选、身份和导入负向回归 |
| `tests/unit/test_parser_provenance.py`、`test_provider_lifecycle.py` | 统计与结果不一致、Audit、取消、目录、worker 和父进程故障注入 |
| `tests/unit/test_cli_log_output.py` | 断言锁定 CLI 为流水线失败输出明确状态并非零退出 |
| `docs/contracts/*`、本审阅 | 两份 V1 说明、两份 JSON Schema、审阅、验收与接入交接 |

## 回滚

使用后续评审认可的逐包补丁，在当前基线或后续合并树逐块核对。先备份未提交改动，并用 `git apply --check -R /path/to/reviewed-task.patch` 验证反向补丁，执行前确认仅包含本任务的 hunk。存在交叠时手工仅撤销本工作块的改动。保留原始 PDF、测试产物与已保存合同证据。

| 工作包 | 撤销范围 | JudgeAI 行为 |
| --- | --- | --- |
| PR4 | Worker 退出校验、故障注入和独立验收脚本 | Core 内部 worker 退出保护取消。父进程的退出校验继续适用 |
| PR3 | 执行统计、最终 manifest 扩展和锁定状态传播 | 旧字段依然可读。V1 JudgeAI 必须拒绝缺失 provenance |
| PR2 | 预检、源码/模型身份、有效配置指纹和 RapidOCR 绑定 | V1 JudgeAI 停止接入，保持缓存隔离 |
| PR1 | 严格 Profile 加载、守卫和旧脚本入口适配 | 显式锁定保证消失。V1 JudgeAI 停止接入 |

## JudgeAI Codex 交接

> 在 JudgeAI 中接入 PDFFast 的权威生产解析配置合同 V1。读取同一 PDFFast 发布源码中的 `docs/contracts/production_parser_identity_v1.md`、`docs/contracts/parser_provenance_v1.md` 和两个 JSON Schema。使用固定独立 Python 3.12 环境及明确的已验证 Profile 路径。通过 `pdffast.preflight_production_profile(config=ParserConfig(...))` 或 `python -m pdffast.preflight --project-root ... --provider-profile ... --json` 预检实际配置并比较部署 pin。embedded runner 应使用与预检同样的 `ParserConfig` 和唯一 run ID 调用 `PDFFastParser`。父进程先拒绝非零退出码，再校验输出、Audit、输入 SHA 和 V1 provenance。要求 `profile_locked=true`、`execution_status=COMPLETED`、失败数 0，配置身份与预检一致，尝试及选中 Provider 是预检允许名单成员。允许 Profile 内回退和 Native-only 零任务。将来源持久化，以 PDF SHA、有效指纹和合同版本隔离缓存，旧缓存须具备匹配 provenance 才可复用。配置、预检、执行、Audit、缺失或不一致来源均使任务 FAILED。HTTP 继续是旧接口范围。当前 PDFFast 工作树源码可用于并行联调。正式部署需等待合入、重新预检并锁定发布身份。
