# B06-A1 Execution Contract V1 合同一致性

## 结论

A1 请求与成功结果合同对齐。本地版本化入口通过参数校验、预检、Core、审计、Manifest 发布与独立验签流程。测试使用 Native PDF 夹具和替换后的运行时身份检查。正式生产环境和真实项目 PDF 留待 A5。

工作在 `/Users/admin/Workspace/pdffast-v3-worktrees/execution-contract-v1`，原始 HEAD 为 `ef225cfb560a03a6f70a90bcf59e929120ec15b4`。远端继承依据和逐文件结果见 [A0 报告](B06-A0_REMOTE_CHANGE_INHERITANCE.md)。

## 实施与证据

| 验收项 | 实施和验证 |
| --- | --- |
| 唯一请求 | `pdffast.execution.request.v1` 包含指定版本、1 至 128 字符的安全 ASCII 标识符、64 位小写 `input.sha256` 和空对象 `options`。本机 PDF 路径、输出根目录和部署配置在请求之外传入。 |
| 调用链 | `PDFFastParser.parse_request()` → `ParseService.parse_request()` → Validator → PDF 摘要匹配 → Profile 与 Preflight → Core → 原有 Builder。Validator、Context 和 Builder 使用同一字典形状。 |
| 输入失败 | 无法读取或空 PDF 抛出 `InputUnavailableError`。摘要错误抛出 `InputIdentityMismatchError` 并保留预期和实际摘要。测试确认这些情况和非法请求均发生在加载 Profile、预检及创建输出目录之前。 |
| 成功合同 | 原有 Provider 执行、版本、配置指纹、实际回退和产物证据保留。新增外层 `status`、`warnings`、`risk_flags`、`error: null` 和根 Manifest 的相对路径。版本化调用回显请求，结果 Schema 使用本机注册的 Request Schema 验证。 |
| 结果状态 | Audit 通过后，含任务失败或终态保留的结果标记为 `PARTIAL_SUCCESS`。对应 Schema 禁止其伪装成 `SUCCESS`。独立生产验收只接受 `SUCCESS`。完全没有可用结果时的失败映射由 A2 验证。 |
| 证据与路径 | Builder 继续计算实际产物 SHA-256、使用 run-relative 路径并拒绝文件或目录软链接。独立验签拒绝摘要被篡改、请求 SHA 与输入身份不一致及产物路径越界。根 Manifest 路径固定为 `result/manifest.json`，其自身摘要由调用方在读取后独立计算。 |
| 信号 | 警告分别取自缺少调用方预期摘要的旧调用、可选预检探测实际未运行、任务失败、终态保留和源码修改状态。风险标记取自这些警告代码。 |
| 兼容 | `PDFFastParser.parse()` 的参数和结果访问方式保留。旧入口的执行合同省略 `request`。成功合同中的路径均为 run-relative，既有内部证据的兼容字段保持原格式。 |

本阶段在原有 Parser、ParseService、PipelineContext 和 Builder 中完成请求接线，更新成功 Schema、请求 Schema、文档、独立验签器和既有测试。Provider Registry、路由、Quality Gate、Fallback、OCR Provider 实现和 CI 工作流的文件 diff 为空。

## 本地验证

- Python 3.12.13 内存编译 90 个 Python 文件。三份 Embedded JSON Schema 通过 Draft 2020-12 结构检查。
- 合同、Parser Provenance、PipelineContext、Production Preflight 和 Native-only 一共 **93 项通过**。
- 加入 Provider 生命周期用例后 **129 项通过、1 项失败**。失败为 `test_mineru_disables_ort_telemetry_before_either_child_starts`，缺少锁定 MinerU tools-config snapshot。A0 已从原始 HEAD 的离线副本复现相同异常。
- `git diff --check` 通过，暂存区为空。执行阶段使用现有虚拟环境和本机 uv 缓存，未安装依赖或运行真实 OCR 模型。

## A2 入口

从 `pdffast/errors.py`、`pdffast/runtime.py`、`pdffast/pipeline/runner.py`、`ParseService`、生产预检和现有 CLI 沿真实异常传播路径接入结构化错误。优先验证 Provider 初始化证据仍能到达调用方、没有可用结果时的失败状态和显式取消。输入仍采用首尾摘要比较，部署端须在执行期间保持文件不变。
