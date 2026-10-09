# v3 独立环境验收与 Git 稳定基线准备

日期：2026-10-09。仓库 `/Users/admin/Workspace/pdffast-v3`，分支 `refactor/v3`，HEAD `dcc7af9`。本轮新增此报告及被忽略的验收产物，只补齐当前v3环境中已声明的测试依赖，没有修改生产代码、测试、配置或锁文件；没有Git暂存、提交、推送、重置或清理。

## 1. 总体结论与冻结范围

**当前本机完整v3环境已独立通过440/20及reference460验收，可以准备依赖闭合的候选代码基线提交。** 不借用pdffast-v2解释器、不复制虚拟环境；候选代码与pytest来自v3。不是全新clone、不含外部fixture的完整复现证明，也不是Linux离线部署或六Provider最新全模型验收。

发现两个可复现交付前置差距：

1. 全新仅dev/service环境缺少HTTP TestClient客户端包。本轮负向实验实际1 failed，并非生产功能回归：当前锁定Starlette1.7.0优先导入httpx2，回退httpx；两者均不在最小extras闭包。应明确支持完整runtime-main验收环境，或后续显式补齐dev客户端声明并同步锁文件，再验收最小测试环境。不能把当前完整环境的通过数字用于宣称最小安装已闭合。
2. 部分测试依赖当前outputs中的冻结Provider产物和旧reference源码/环境/PDF。它们没有进入Git，新clone缺失会增加skip或不能执行reference。需要受控fixture供应与hash/授权说明；禁止本轮复制/修改冻结文件。

上述阻止的是“仅Git+dev/service即可零缺口复现”承诺；没有发现阻止当前本机候选快照冻结的新生产P0。正式提交内容须由用户确认，当前未提交。

## 2. 实际环境与依赖检查

| 项目 | 实测 |
|---|---|
| Python | /Users/admin/Workspace/pdffast-v3/.venv/bin/python，CPython3.12.13 |
| sys.prefix | /Users/admin/Workspace/pdffast-v3/.venv |
| pytest | /Users/admin/Workspace/pdffast-v3/.venv/lib/python3.12/site-packages/pytest/__init__.py，9.1.1 |
| pdffast | /Users/admin/Workspace/pdffast-v3/pdffast/__init__.py，editable当前仓库 |
| FastAPI/Uvicorn | v3/.venv/lib/python3.12/site-packages，0.141.1 / 0.54.0 |
| site-packages | 仅v3自身site目录；pyvenv.cfg include-system-site-packages=false |
| 基础Python标准库 | uv管理的 /Users/admin/.local/share/uv/python/cpython-3.12...，不是v2 site-packages |

初始v3解释器存在，但pytest查找结果None。按项目现有dev/service extras执行 `uv sync --frozen --inexact --extra dev --extra service`，只新增pytest9.1.1/iniconfig2.3.0/pluggy1.6.0/pygments2.21.0。--inexact保留已有Provider包，没有移除/升级模型环境。

根pyproject要求Python>=3.12；Provider子项目明确3.12范围，本轮主环境与Provider均为3.12。默认uv在另一临时最小安装探针选择过3.14.6；这不是基线验收解释器。随后明确--python .venv/bin/python建立全新3.12探针，缺少客户端的结论来自该3.12环境。

实际命令：

```sh
UV_CACHE_DIR=/private/tmp/pdffast-v3-uv-cache uv lock --check --offline
UV_CACHE_DIR=/private/tmp/pdffast-v3-uv-cache uv sync --frozen --inexact --extra dev --extra service
UV_CACHE_DIR=/private/tmp/pdffast-v3-uv-cache uv sync --frozen --extra dev --extra service --extra runtime-main --dry-run
```

根lock check通过（96 packages），三个子项目lock check也通过：MinerU109、Docling129、Marker103。根完整extras dry-run检查93已安装包，Would make no changes。根uv.lock无Git diff，pyproject仍只有本轮前已有模板wheel项删除。默认uv缓存因sandbox不可写，使用/tmp独立缓存；下载仅依赖包，没有模型下载。

最小extras的dry-run会卸载59额外包，包括httpx/httpx2和主Provider依赖，所以**不能在当前运行环境执行最小exact sync来整理包**。本轮只dry-run，未卸载。

## 3. Provider与Reference边界

生产六Provider：PaddleOCR文本、PaddleOCR-VL、RapidOCR在主进程环境；Docling/MinerU/Marker分别指向v3/runtimes/<provider>/.venv/bin/python。实际执行这些解释器的sys.prefix/site/sys.path检查，均指向自身v3子环境且无v2 site-packages，没有导入重型模型。

runtimes/mineru/pyproject.toml仍锁mineru[pipeline]3.4.5、torch2.14.0、torchvision0.29.0、six1.17.0、onnxruntime1.30.0、transformers4.57.6。未升级版本。

模型资源部分共享HOME缓存，Marker HOME仍包含`${HOME}/Library/Caches/pdffast-v2/marker-workers/${PDFFAST_WORKER_ID}`历史目录名：这是缓存隔离布局，不是导入v2代码或借v2解释器，但迁移/离线部署仍须按已冻结配置准备路径。本轮不改配置、不验证所有模型可推理。

Reference-bound候选pytest全部由v3执行，清除PYTHONPATH。`tests/regression/test_profiler_parity.py:43`明确启动`PDFFAST_REFERENCE_ROOT/.venv/bin/python`运行旧scripts/1_page_profiler.py生成oracle；旧Normalizer由test_prediction_normalizer_parity.py的spec_from_file_location加载单独参考模块。其余参考源码manifest/config/PDF属于对照输入。reference本身因此仍有旧环境/源码运行依赖，不能称为纯数据或完全无旧项目执行的测试。

`tests/conftest.py`仅一个旧v2说明docstring，没有修改sys.path或加载v2 site-packages。正式parse不读取PDFFAST_REFERENCE_ROOT启动旧项目。candidate/native、HTTP、Worker代码依旧来自v3。

## 4. 本轮实际测试

所有主验收命令均在v3 cwd使用 `.venv/bin/python -m pytest`，未用v2 Python。禁用pyc与pytest cache避免改参考/额外缓存；测试tmp产物独立目录。

```sh
env -u PYTHONPATH -u PDFFAST_REFERENCE_ROOT -u PDFFAST_SAMPLE_PDF \
 PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider \
 --basetemp=/private/tmp/pdffast-v3-independent-full-20261009 tests/unit tests/contracts tests/regression

env -u PYTHONPATH PDFFAST_REFERENCE_ROOT=/Users/admin/Workspace/pdffast \
 PDFFAST_SAMPLE_PDF=/Users/admin/Workspace/pdffast/benchmark/samples/real/case_002.pdf \
 PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider \
 --basetemp=/private/tmp/pdffast-v3-independent-reference-20261009 tests/unit tests/contracts tests/regression

env -u PYTHONPATH PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider \
 --basetemp=/private/tmp/pdffast-v3-independent-focused-20261009 \
 tests/unit/test_provider_lifecycle.py tests/unit/test_shutdown_cleanup.py \
 tests/unit/test_service_shutdown.py tests/unit/test_supplemental_evidence.py \
 tests/unit/test_supplemental_diagnostics.py tests/unit/test_runtime_logging_integration.py
```

| 验证 | 本轮结果 | 秒 |
|---|---|---:|
| 完整unit/contracts/regression | 440 passed、20 skipped、0 failed | 34.22 |
| reference-bound完整 | 460 passed、0 failed | 146.41 |
| HTTPv1/生命周期/Supplemental/真实Uvicorn退出专项 | 78 passed、0 failed | 9.90 |
| 全新3.12最小dev/service的单一HTTP合同负向探针 | 1 failed：缺少httpx2/httpx，尚未进入parse | 1.99 |
| git diff --check | 通过 | — |

专项是全套的子集，不能相加作为独立总数。20skip全部为未设置reference/sample：snapshot_section2、snapshot_structure3、frozen_config1、source_baseline2、generic_native_sections2、generic_section_continuation2、prediction_normalizer7、profiler1。没有把Provider失败当skip。

全新负向探针命令：

```sh
UV_PROJECT_ENVIRONMENT=/private/tmp/pdffast-v3-minimal312-dev-service-20261009 \
 UV_CACHE_DIR=/private/tmp/pdffast-v3-uv-cache uv sync --frozen --python .venv/bin/python --extra dev --extra service
env -u PYTHONPATH PYTHONDONTWRITEBYTECODE=1 \
 /private/tmp/pdffast-v3-minimal312-dev-service-20261009/bin/python -m pytest -q -p no:cacheprovider \
 tests/unit/test_runtime_logging_integration.py::test_http_v1_response_and_concurrent_request_run_ids
```

未删除测试或放宽断言，未把预期环境缺口失败合并进主环境的通过数字。tests/unit/test_supplemental_evidence.py129附近及raw_provider_normalizer_handoff读取本地outputs的冻结输入：当前存在才通过，新的clone需显式供应。参考PDF及Provider raw产物不是本轮新推理。未运行tests/provider重型模型或完整case003。

## 5. 服务入口与退出实测

`pdffast/service/__main__.py:build_config`从PDFFAST_SHUTDOWN_GRACE_SECONDS读取宽限，默认30秒且校验有限正数；默认端口8020。lifespan cleanup窗口另由PDFFAST_SHUTDOWN_CLEANUP_SECONDS默认30秒控制。使用泛用uvicorn命令仍需显式--timeout-graceful-shutdown 30。

本轮由v3解释器实际启动`python -m pdffast.service`，只覆盖PDFFAST_PORT为随机隔离端口，不替换app或Parser。真实结果：

- 主进程PID：20888，端口：63111（非8010/8011）。
- GET /health：200，返回 `{"status": "UP"}`。
- SIGINT退出：0.285秒，returncode=-2；Uvicorn重发信号，不能仅凭负退出码判资源泄漏。

- SO_REUSEADDR后可重新bind/listen，同端口connect失败，监听已释放。首轮不设置reuse时遇EADDRINUSE；TCP关闭状态不等于仍有监听服务，保留初始日志，不修改生产代码。
- 无解析请求，没有启动Worker/心跳。10种真实信号/Worker/失败/超时场景已在本轮78专项及完整套件通过。
- 进程内Native/C永久阻塞不可安全强制取消仍是已知边界；本轮不扩大关闭承诺。

原始证据位于outputs/v3_independent_environment_validation/20261009/service-entry.json及service-entry-verified.log，均被Git忽略。未操作8010、8011或JudgeAI，未全局pkill/killall。

## 6. Git只读盘点与依赖关系

已执行git status、git diff --stat、git diff --check、git log、git ls-files及未跟踪/忽略文件盘点，读取.gitignore。HEAD dcc7af9已有编号重启及Template移除等早期提交；本轮前28tracked文件修改，1813insertions/236deletions。盘点时97个untracked，本报告随后增加1；不能用tracked diff统计替代全部新文件数量。

无tracked或未忽略untracked单文件超过1MiB，未见模型/大型输出进入候选集。114543个ignored文件主要处于模型环境/outputs/缓存；这不是拟提交数量。`.gitignore`覆盖.venv/.venv-*/outputs/__pycache__/pyc/log/PDF。临时`:memory:.ses`必须排除但本轮保留不删。runtimes/*/uv.lock是需要保留的依赖声明，不是缓存。

当前功能分类及跨文件依赖：

| 类别 | 关键文件/关系 | 拆分限制 |
|---|---|---|
| R2结构语义 | native/sections → structure_reconciliation → canonical/audit document_units → render | Canonical与Audit/Renderer及新contract共同闭合，不可只提交新class或runner |
| R3对象链/R4路径 | profiler/structure/tables/text_flow/evidence → pipeline/artifacts/runner → Canonical/Audit | runner直接消费新增对象与路径视图，旧消费者/接口测试必须一起提交 |
| Provider依赖修复 | runtimes/mineru声明及锁 + mineru/workers/dependency tests | workers同文件叠加capture/取消，当前文件级stage不能单独隔离旧修复 |
| Runtime中文日志 | runtime → runtime_format；ParseService/runner/executor发事件 | 不提交Formatter会导致runtime导入失败 |
| 退出可靠性 | service app/__main__ → runtime取消 → executor/workers清理 | 与当前日志/capture同文件交织，不能只stage service |
| Supplemental对象及诊断 | base/mineru_capture/supplemental/workers → runtime_normalization/normalization → executor/formatter | Raw对象/IPC/Normalizer/diagnostics测试必须同版本，不可机械按历史阶段切提交 |
| 测试与报告 | 同步契约、冻结样本/replay及阶段报告 | 测试归功能提交；文档历史数字需标明当时环境，外部outputs不进Git |

## 7. 推荐最终提交方案（尚未执行）

**推荐3个逻辑提交：一个依赖闭合的集成实现+测试+MinerU锁定提交，随后报告，最后可选离线实验。** 不声称已构造/验收多个部分checkout。若坚持按架构/Provider/日志/退出/证据分多个代码提交，须未来先在隔离checkout逐hunk构造并独立验收，不能把当前相互依赖文件机械拆成不可测试中间状态。

### 提交1：完整v3集成代码与同步测试

包含下列77个变更文件；这是一份显式清单，不是git add .。root uv.lock当前无diff，保留已有tracked版本；runtimes/mineru锁与声明同提交。验证门槛：此处440/20、460、78专项、锁文件check、HTTP入口、git diff --check。正式提交前再次确认文件清单且不得包含本轮之外新增未审查修改。

- `pdffast/application/parse_service.py`
- `pdffast/audit/_stage10_audit.py`
- `pdffast/audit/structure_boundary.py`
- `pdffast/canonical/_stage10_builder.py`
- `pdffast/canonical/builder.py`
- `pdffast/fallback/executor.py`
- `pdffast/native/profiler.py`
- `pdffast/native/sections.py`
- `pdffast/native/structure.py`
- `pdffast/native/tables.py`
- `pdffast/native/text_flow.py`
- `pdffast/pipeline/artifacts.py`
- `pdffast/pipeline/runner.py`
- `pdffast/providers/base.py`
- `pdffast/providers/mineru.py`
- `pdffast/providers/normalization.py`
- `pdffast/providers/runtime_normalization.py`
- `pdffast/providers/workers.py`
- `pdffast/quality/evidence.py`
- `pdffast/render/_stage10_renderer.py`
- `pdffast/runtime.py`
- `pdffast/service/app.py`
- `pyproject.toml`
- `runtimes/mineru/pyproject.toml`
- `runtimes/mineru/uv.lock`
- `tests/unit/test_generic_sections.py`
- `tests/unit/test_phase4_core.py`
- `tests/unit/test_provider_lifecycle.py`
- `pdffast/audit/document_units.py`
- `pdffast/canonical/document_units.py`
- `pdffast/providers/mineru_capture.py`
- `pdffast/providers/supplemental.py`
- `pdffast/runtime_format.py`
- `pdffast/service/__main__.py`
- `pdffast/structure_reconciliation/__init__.py`
- `pdffast/structure_reconciliation/adjudication.py`
- `pdffast/structure_reconciliation/anchor_admission.py`
- `pdffast/structure_reconciliation/coverage.py`
- `pdffast/structure_reconciliation/document_units.py`
- `pdffast/structure_reconciliation/heading_candidates.py`
- `pdffast/structure_reconciliation/page_relations.py`
- `pdffast/structure_reconciliation/preview.py`
- `tests/fixtures/service_shutdown_lab.py`
- `tests/regression/test_canonical_document_units_case003.py`
- `tests/regression/test_document_anchor_admission_case003.py`
- `tests/regression/test_document_coverage_case003.py`
- `tests/regression/test_document_unit_audit_cases.py`
- `tests/regression/test_document_unit_case003.py`
- `tests/regression/test_generic_section_continuation.py`
- `tests/regression/test_page_relations_case003.py`
- `tests/unit/test_canonical_document_units.py`
- `tests/unit/test_document_anchor_admission.py`
- `tests/unit/test_document_coverage.py`
- `tests/unit/test_document_range_semantics.py`
- `tests/unit/test_document_unit_audit.py`
- `tests/unit/test_document_unit_contract.py`
- `tests/unit/test_document_unit_renderer.py`
- `tests/unit/test_mineru_dependencies.py`
- `tests/unit/test_page_relations.py`
- `tests/unit/test_raw_provider_normalizer_handoff.py`
- `tests/unit/test_reconciled_structure_preview.py`
- `tests/unit/test_recovered_heading_candidates.py`
- `tests/unit/test_recovered_structure_adjudication.py`
- `tests/unit/test_runtime_chinese_format.py`
- `tests/unit/test_runtime_logging_integration.py`
- `tests/unit/test_runtime_observation.py`
- `tests/unit/test_selected_stage10_object_handoff.py`
- `tests/unit/test_semantic_artifact_paths.py`
- `tests/unit/test_semantic_runner_wiring.py`
- `tests/unit/test_service_shutdown.py`
- `tests/unit/test_shutdown_cleanup.py`
- `tests/unit/test_snapshot_section_handoff.py`
- `tests/unit/test_snapshot_structure_handoff.py`
- `tests/unit/test_stage10_remaining_object_inputs.py`
- `tests/unit/test_supplemental_diagnostics.py`
- `tests/unit/test_supplemental_evidence.py`
- `tests/unit/test_table_result_handoff.py`

### 提交2：审查与验收报告

依赖提交1，用下面报告清单加本报告；历史报告代表对应阶段证据，不改写历史命令/数字为当前460，不混淆旧v2解释器与本轮v3验收。当前报告有PDF摘录/本地路径，正式共享前确认内容授权及敏感信息；不默认归档原PDF。验证Markdown文件引用与历史结果边界，不需重复重型推理。

- `docs/reviews/case003-performance-diagnosis.md`
- `docs/reviews/case003-quality-acceptance-diagnosis.md`
- `docs/reviews/final-structure-regression.md`
- `docs/reviews/mineru-case003-pages43-44-validation.md`
- `docs/reviews/mineru-runtime-dependency-fix.md`
- `docs/reviews/mineru-supplemental-blocks-experiment.md`
- `docs/reviews/native-recovered-coverage-experiment.md`
- `docs/reviews/r2-e3b-page-ownership.md`
- `docs/reviews/r2-e4b-recovered-heading-candidates.md`
- `docs/reviews/r2-e4c-recovered-structure-proposals.md`
- `docs/reviews/r2-e4d-reconciled-structure-preview.md`
- `docs/reviews/r2-e4e1-document-unit-contract.md`
- `docs/reviews/r2-e4e2a-document-range-evidence.md`
- `docs/reviews/r2-e4e2b-page-relations.md`
- `docs/reviews/r2-e4e2c-document-coverage-resolution.md`
- `docs/reviews/r2-e4e2c0-document-range-semantics.md`
- `docs/reviews/r2-e4e2c1-document-anchor-admission.md`
- `docs/reviews/r2-e4e3-canonical-document-units.md`
- `docs/reviews/r2-e4e4-document-unit-rendering.md`
- `docs/reviews/r2-e4e5-document-unit-audit.md`
- `docs/reviews/r3-b0-native-runtime-dependency-audit.md`
- `docs/reviews/r3-b10-post-native-runtime-dependency-audit.md`
- `docs/reviews/r3-b11-selected-predictions-stage10-object-handoff.md`
- `docs/reviews/r3-b12-stage10-object-input-convergence.md`
- `docs/reviews/r3-b13-audit-object-input-convergence.md`
- `docs/reviews/r3-b14-raw-provider-normalizer-object-handoff.md`
- `docs/reviews/r3-b15-final-runtime-dependency-audit.md`
- `docs/reviews/r3-b2-snapshot-section-object-handoff.md`
- `docs/reviews/r3-b3-snapshot-page-structure-object-handoff.md`
- `docs/reviews/r3-b4-section-structure-object-handoff.md`
- `docs/reviews/r3-b5-profile-structure-object-handoff.md`
- `docs/reviews/r3-b6-structure-table-object-handoff.md`
- `docs/reviews/r3-b7-snapshot-table-object-handoff.md`
- `docs/reviews/r3-b8-textflow-object-input-convergence.md`
- `docs/reviews/r3-b9-evidence-object-input-convergence.md`
- `docs/reviews/r4-a-artifact-output-taxonomy-audit.md`
- `docs/reviews/r4-b-semantic-artifact-layout-contract.md`
- `docs/reviews/refactor-closeout-audit.md`
- `docs/reviews/runtime-logging-chinese-format.md`
- `docs/reviews/runtime-logging-heartbeat.md`
- `docs/reviews/service-shutdown-reliability.md`
- `docs/reviews/supplemental-evidence-contract.md`
- `docs/reviews/supplemental-evidence-diagnostics.md`
- `docs/reviews/supplemental-evidence-live-validation.md`
- `docs/reviews/v3-independent-environment-and-git-baseline.md`

### 提交3（可选）：离线实验原型

- `experiments/case003_quality/offline.py`
- `experiments/case003_quality/run.py`
- `experiments/case003_quality/test_offline.py`

只在独立实验范围与输入供应说明获确认时纳入。正式Runtime无experiment依赖。验证入口是实验自己的test_offline.py（本轮未执行，既有完整tests不覆盖它），以及冻结输入hash清单/人工证据。当前实验依赖本机outputs，不能宣称提交这3文件就供应了实验数据；可延后提交，不阻塞生产候选代码。

### 必须排除

`:memory:.ses`、.venv及子环境、模型权重/模型缓存、outputs全部真实PDF/实验/性能/服务日志、临时/tmp环境、pytest/pyc缓存、原始用户PDF。它们本轮全部保留，不清理。报告引用的本机outputs作为证据位置，不是Git artifact要求。若需要归档冻结样本，另行受控包及hash manifest，而非取消ignore或git add -f。

## 8. 提交前最小行动与结论边界

1. 用户确认提交1闭合集合及报告共享范围；本轮只计划，不暂存或提交。
2. 明确正式验收安装合同：Python3.12 + dev/service/runtime-main，并记录外部Provider/model/reference fixture需求；如需轻量dev/service独立测试，先补齐测试客户端声明并复测。不要借Provider偶然转依赖声称最小合同已稳定。
3. 明确reference oracle版本及冻结输出供应；当前reference运行依赖是合理测试对照，但不能混同生产运行依赖。
4. 下一次正式提交前复查差异/文件清单、无模型/临时产物，保持本轮验证对象一致；打tag/push也须单独确认。

未新发现本机候选生产P0。可准备集成候选提交；**仍不建议承诺Git-only clean clone全套460、最小dev/service全通过、Linux离线交付、修复后完整case003质量/性能、所有Native挂死可硬退出。** 本轮环境补齐不改变解析结果、HTTPv1、Router/Acceptance、Canonical、Markdown、Audit或心跳。


## 9. 2026-10-09 测试依赖修复与正式候选提交验收

本节记录后续获批的本地提交任务，以上章节保留此前审查时的状态与历史测试数字。用户已批准两个本地提交，禁止push/merge/清理；此前“未提交”描述属于当时审查状态。

### 缺口归因与修复

`tests/unit/test_runtime_logging_integration.py:164`导入FastAPI TestClient。现有dev声明pytest，service声明FastAPI/ASGI运行库，测试代码仅在FastAPI缺失时skip，因此dev+service应当支持HTTP合同测试。当前Starlette1.7.0优先使用httpx2，回退httpx且标记deprecated。修复采用 **dev extra增加httpx2>=2.13.1**；未加入project.dependencies或service生产extras。

先在此前干净Python3.12 dev/service环境重现1 failed（TestClient导入缺少客户端），再更新声明及根uv.lock。根锁diff仅两处dev依赖/metadata引用，原96包版本全部保持，生产服务依赖逐项比较不变。离线缓存最初缺Provider包索引元数据，联网完成uv lock解析，未模型下载/升级。

### 干净环境验证

使用新的环境而非向旧失败环境手工pip补包：

```sh
UV_PROJECT_ENVIRONMENT=/private/tmp/pdffast-v3-clean-declared-test-20261009 \
 UV_CACHE_DIR=/private/tmp/pdffast-v3-uv-cache \
 uv sync --frozen --python .venv/bin/python --extra dev --extra service
```

Python为3.12.13，安装37个锁定包；pytest、httpx2及service库均来自该临时环境，pdffast editable指向当前v3仓库，sys.path无v2。实际检查RapidOCR/PaddleOCR/Torch/MinerU/Docling/Marker均不存在；不会因模型环境提供间接测试依赖而通过。

原失败HTTPv1及并发run_id用例：**1 passed，1.62秒**。完整unit/contracts/regression：**440 passed、20 skipped、0 failed，38.91秒**。Reference-bound全套：**460 passed、0 failed，144.83秒**。所有本轮适用测试已通过，没有未解决失败。

完整测试使用上述干净环境的bin/python执行，与上一节含runtime-main的本机环境结果严格区分：

```sh
env -u PYTHONPATH -u PDFFAST_REFERENCE_ROOT -u PDFFAST_SAMPLE_PDF \
 PYTHONDONTWRITEBYTECODE=1 /private/tmp/pdffast-v3-clean-declared-test-20261009/bin/python \
 -m pytest -q -p no:cacheprovider --basetemp=/private/tmp/pdffast-v3-baseline-clean-full-20261009 \
 tests/unit tests/contracts tests/regression

env -u PYTHONPATH PDFFAST_REFERENCE_ROOT=/Users/admin/Workspace/pdffast \
 PDFFAST_SAMPLE_PDF=/Users/admin/Workspace/pdffast/benchmark/samples/real/case_002.pdf \
 PYTHONDONTWRITEBYTECODE=1 /private/tmp/pdffast-v3-clean-declared-test-20261009/bin/python \
 -m pytest -q -p no:cacheprovider --basetemp=/private/tmp/pdffast-v3-baseline-clean-reference-20261009 \
 tests/unit tests/contracts tests/regression
```

最小dev/service环境依赖缺口已解决；外部reference oracle、PDF、outputs冻结输入依赖仍保留，不声称Git-only clone供应这些资源。未修改测试断言、增加skip或删除测试；未重跑完整case003。

### 正式提交范围

核心计划清单在原第7节77文件基础上增加根`uv.lock`，共78文件。通用结构/DocumentUnit、对象链/语义ArtifactPaths、Provider依赖/生命周期、中文Runtime日志/心跳、服务关闭、Supplemental合同/诊断及同步测试纳入同一个依赖闭合提交。根pyproject同时保留之前Template wheel条目删除和本轮dev依赖修复。

正式报告共45个Markdown文件，现有最大单文件约26KiB，总约448KiB（本节追加前）；不存在大运行产物。链接文件检查无缺失；历史绝对路径作为取证记录，不冒充部署路径。常见私钥/API凭据模式扫描未命中，不等同完整安全审计。

离线实验3个源码文件及`:memory:.ses`继续留在工作区、不暂存、不删除。outputs、模型、环境、日志/缓存均不提交。首次检查index为空，无来源不明暂存。提交必须按显式文件清单、核对cached name-status/stat/check后执行，不使用git add .或git add -A。

### JudgeAI集成边界

可以开始隔离的v3 HTTP集成验收；不是直接批准正式地址切换。六Provider完整最新推理、修复后的整份case003质量/性能、Linux CPU离线部署仍未由本轮验收覆盖。Native/C永久阻塞不可安全强制中断、Acceptance/Audit不保证OCR逐字真实性的既有限制仍保留。Supplemental仍不自动进入正文。


### 核心提交与剩余工作区

核心本地提交：`923d035c6aeeba7aab231c30ebeb4844cdf1bc8a`，消息`refactor: consolidate PDFFast runtime and parsing architecture`。78文件，8801 insertions/237 deletions；暂存blob SHA256逐项等于已通过干净环境测试的文件，cached name-status/stat/check通过。未包含docs、outputs或experiments。Git使用本机现有自动配置的提交身份，未修改Git身份配置。

第二个提交仅包含45份正式审查/实现/验证报告（含本报告），消息`docs: record PDFFast refactor and validation results`。实验代码不是生产运行依赖，不纳入此次基线。保留的非正式文件：

- `experiments/case003_quality/offline.py`：离线原型。
- `experiments/case003_quality/run.py`：离线实验入口，依赖冻结outputs。
- `experiments/case003_quality/test_offline.py`：实验专项测试，非正式测试提交范围。
- `:memory:.ses`：本机临时session文件。

所有ignored outputs/模型/虚拟环境/cache原样保留，不push、merge、reset、clean或自动提交可选实验。不重跑完整case003。
