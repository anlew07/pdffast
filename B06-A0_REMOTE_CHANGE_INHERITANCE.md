# B06-A0 远端修改盘点与本地继承

## 基线

- 工作目录为 `/Users/admin/Workspace/pdffast-v3-worktrees/execution-contract-v1`。原始 HEAD 为 `ef225cfb560a03a6f70a90bcf59e929120ec15b4`，处于 detached HEAD。
- 开始时暂存区和已跟踪工作区均无修改。原有未跟踪路径为 `.venv`、`runtimes/indra/`、`runtimes/mineru/.venv`，均保留。
- `origin` 的 fetch 和 push URL 均为 `git@github-anlew07:anlew07/pdffast.git`。主工作区在 `feat/pdffast-production-governance-v1` 的 `da63ce943a2ae763d5aad17da8f042f4f5535330`，已有未暂存的 `tests/unit/test_provider_lifecycle.py` 修改，保留在主工作区。
- 仅获取指定分支 `feat/pdffast-execution-contract-v1`。远端跟踪引用由 `ef225cf` 更新到 `363a809bb2103e8e44faee65344298cbc6022164`，与指定提交一致。两者的共同祖先是本地 HEAD，差额为 24 个提交、15 个文件。
- 以已有目标引用 `origin/feat/pdffast-production-governance-v1@0d497ebe3ca416d865a3cd16994d444bdde1e00f` 核对 [PR #7](https://github.com/anlew07/pdffast/pull/7) 所述 72 个提交、18 个文件。该范围包含本地已经具备的 Builder、结果/溯源接口和测试。

## 逐文件处理

| 文件 | 本地状态 | 远端状态 | 处理方式 | A0 结果 |
| --- | --- | --- | --- | --- |
| `pdffast/application/execution_contract.py` | 已有 Builder 和产物摘要 | 增加 Validator、请求回显、风险信号 | B | 保留 Builder 和证据结构，Validator、回显及信号在 A1 同步移植 |
| `pdffast/application/parse_service.py` | 预留和 Core 各自处理输出根目录 | 统一根目录，并新增扁平请求检查和 SHA 校验 | B | 只应用 `4103b9b` 的根目录补丁，其余与 A1 合并 |
| `pdffast/errors.py` | 已有 Preflight、执行、Audit 等异常 | 增加输入错误和序列化 | B | 输入错误与 A1 请求接线合并，整体错误响应与 A2 合并 |
| `pdffast/parser.py` | 已有 `parse()` | 增加 `parse_request()` 并合成内部请求和覆盖项 | B | 沿用入口形态，A1 以单一请求接线 |
| `pdffast/pipeline/context.py` | 已有输入身份 | 新增请求字段 | B | 随 A1 Service 和 Builder 接线一起继承 |
| `pdffast/pipeline/runner.py` | 已有审计、Builder 和发布门禁 | 新增异常时的观察信息读取 | C | A2 验证观察阶段和 Provider 证据在异常传播时是否仍在作用域内 |
| `pdffast/result.py` | 已经暴露合同和证据路径 | 内容相同 | D | 保留本地实现 |
| `pdffast/runtime.py` | 已有生命周期和取消观测 | 增加失败快照接口和独立取消序列化 | C | A2 用现有 Observer 接通实际异常链 |
| `docs/contracts/embedded_execution.v1.schema.json` | 已有成功 Schema 和证据约束 | 增加扁平回显和诊断字段 | B | A1 保留已有约束，统一请求和响应字段 |
| `docs/contracts/embedded_execution_request.v1.schema.json` | 缺失 | 允许 DPI、RapidOCR worker 数和表格模式 | C | 保留外层形状，A1 收敛选项并补齐 Python 与 Schema 边界一致性 |
| `docs/contracts/embedded_execution_error.v1.schema.json` | 缺失 | 定义错误响应及状态 | A | 原样继承为 A2 的起点 |
| `docs/contracts/embedded_execution_v1.md` | 已有设计草案 | 内容相同 | D | 保留原文供 A1 对照更新 |
| `pyproject.toml` | 合同测试已使用 jsonschema，开发依赖未声明 | 增加 jsonschema 开发依赖 | B | 纳入远端声明，生产依赖未增加 |
| `scripts/verify_production_governance.py` | 已有独立溯源和摘要核验 | 增加 Schema 校验、基于目录描述符的单次读取和结构化验签失败 | B | 保留原有验签规则，继承单次读取与实质变更 |
| `tests/unit/test_embedded_execution_contract.py` | 已覆盖 Builder、摘要和 Fake Provider 降级证据 | 增加单次读取、Schema 和链接检查 | B | 保留全部本地覆盖并合并远端测试 |
| `tests/unit/test_parser_provenance.py` | 已有本地真实 Core 调用和篡改验证 | 内容相同 | D | 原样保留 |
| `tests/unit/test_pipeline_context.py` | 已有上下文测试 | 增加锁定及非锁定模式的输出根目录用例 | B | 合并远端回归用例 |
| `.github/workflows/production-governance-v1.yml` | 已有工作流 | 存在远端差异 | D | 保留本地文件 |

实际继承 6 个文件，分别为 ParseService、错误 Schema、开发依赖声明、验签脚本和两份测试。选定补丁的共同基线与原始 HEAD 相同，各重叠文件的工作区无用户变更，补丁直接应用且无冲突标记。其余文件如表所示留在本地基线或进入后续对齐范围。

## 十项远端风险核对

| 项目 | 远端证据与处理 |
| --- | --- |
| Validator 与 Service | Validator 返回嵌套 `input.sha256`，Service 要求扁平 `input_sha256`。`parse_request()` 另行变形才接通。A1 统一结构。 |
| Builder 与 Success Schema | Builder 直接回显 `context.execution_request`。远端 Schema 匹配 facade 合成的扁平结构，直接传入 Validator 返回值则不匹配。 |
| Validator 入口 | facade 调用 Validator。Service 通过局部 `get()` 检查收到的内部字典，并未调用 Validator。 |
| 错误传播 | 远端异常支持 `to_contract()`，请求 Validator 仍抛普通 `ValueError`，`scripts/run_pipeline.py` 仍只调用旧入口，缺少结构化失败输出。 |
| Provider 初始化 | 远端 runner 在异常退出后读取 Observer。锁定模式可能已经退出 runner 自己打开的观测作用域，声明了字段仍需沿实际失败路径测试。 |
| 运行风险 | 远端依赖探测、终态保留、任务失败和代码修改信号有真实来源。`INPUT_NOT_SNAPSHOTTED` 无条件加到风险数组，A1 排除这项常量标记。 |
| SHA-256 | Builder 对实际文件哈希，独立验签绑定 Manifest 输入、证据和真实产物。A0 继承同一字节快照的摘要及 JSON 检查。根 Manifest 通过固定路径定位，自身不进入内嵌摘要数组。 |
| 部分失败 | 内部已有 `COMPLETED_WITH_PIPELINE_FAILURES`，完整验收要求零失败。公开成功形状仍缺少独立的 `status`，A2 明确部分成功和完全失败映射。 |
| 测试入口 | 现有用例覆盖 Core、Fake Provider 和产物验签。远端增量尚缺 Validator 到真实 ParseService 再到结构化回执的用例。 |
| 重复与依赖 | 复用现有 Builder、结果类和验签器。`jsonschema` 只列为开发依赖，便于现有验签工具和测试按 Schema 验证。 |

## 验证与剩余问题

- 新继承用例在实现补丁应用前有 5 项按预期失败，覆盖两条输出根目录分支和三项验签路径。
- 合同、溯源、PipelineContext、生产预检共 49 项通过。加入 Provider 生命周期后为 85 项通过、1 项失败。
- `test_mineru_disables_ort_telemetry_before_either_child_starts` 因缺少锁定 MinerU tools-config snapshot 失败，在原始 HEAD 的临时离线归档单独运行复现同一异常。
- Python 3.12.13 内存编译 89 个源码文件。Draft 2020-12 检查通过。现有虚拟环境缺少 `jsonschema`，测试通过 `PYTHONPATH` 使用已有本机 uv 缓存，未安装依赖。
- A1 的入口为 `PDFFastParser.parse_request()` → `ParseService` → Core → 现有 Builder。按要求将选项保持为空，校验时机放在锁定预检和 run 预留之前，保留现有 Provider、溯源、摘要及路径证据。A2 负责最终错误传播与状态语义，真实 PDF 和 JudgeAI 交付仍待 A5。
