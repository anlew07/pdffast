# PDFFast V3 Core Pipeline

`PDFFastParser.parse()` 为每次解析使用独立 `run_id` 输出目录，保存最终 Markdown、Canonical JSON、Audit、输入 Manifest，以及可选的过程诊断和 Provider 原始产物。

## 对象化执行

`run_core_pipeline()` 统一协调 Native → Evidence → Quality Gate → Fallback Planning → Capability Routing → Provider Policy → Provider Executor → Canonical Builder → Renderer → Audit。

同一次正式解析的计算结果主要通过 Python 对象传递。中间 JSON、Provider 文件和结构化事件保留取证/回放价值，但不是 Core 的 File Bus。历史编号（例如部分函数名或 Manifest 的 `stage` 字段）仍保留以兼容既有工具，不应再用于描述架构分层。

当前正式入口始终传入 `execute_providers=True` 及 Provider 配置、Registry、Normalizer。直接调用 `run_core_pipeline(..., execute_providers=False)` 可能先生成规划产物，但**当前实现会明确抛出异常**，不是受支持的纯规划成功模式。

## Provider 执行

执行器按候选链进行确定性升级波次，同一运行内复用已初始化的 Provider，并在 `finally` 中尝试关闭已创建的实例。生产闭包验证会在 Provider 实际创建前检查配置的启用状态和可解析性。

未显式指定锁定 Profile 时，默认冻结候选链仍由既有六个内置 Provider 及候选顺序控制。Indra 通过 `plugins` 显式注册，但不在默认冻结候选链中；只有在 `provider_chain_overrides` 或锁定 Profile 中被明确选入后才会参与执行。当前 `configs/profiles/production.indra-triple.json` 是显式锁定的 Indra + RapidOCR + MinerU 候选组合，不等于默认 Provider 集合，也不代表已经完成正式生产发布。扩展 Provider 必须显式注册其 Adapter/Normalizer。详见 [插件接入说明](PROVIDER_PLUGINS_ZH.md)。

运行结果会包含 `production_execution_manifest.json` 与 `selected_prediction_index.json` 等可追踪产物；它们用于审查执行过程和选择依据，不取代真实内容准确率评测。

## 成功语义

普通解析使用 `ParseResult` 的 Markdown、Canonical 与 Audit。锁定 Profile 的版本化解析还会发布带输入身份、配置指纹和产物摘要的 [Embedded V1 回执](contracts/embedded_execution_v1.md)。完整结果外层状态为 `SUCCESS`；Audit 通过且有可用内容、同时存在终态保留时为 `PARTIAL_SUCCESS`。未解决的 Provider 任务失败、渲染校验失败或没有可用正文会阻止发布可用结果。

Provider 的 `SUCCESS`、执行器接受结果和 Audit PASS 均不等于 OCR 内容逐字正确。Audit 核验的是结构、来源与渲染合同；业务准确率需要通过带 Ground Truth 的 PDF Benchmark 单独量化。
