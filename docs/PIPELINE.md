# PDFFast V3 Core Pipeline

`PDFFastParser.parse()` 为每次解析使用独立 `run_id` 输出目录，内部路径按 `native/quality/fallback/providers/canonical/render/audit` 分组，保存最终 Markdown、Canonical JSON、Audit、输入 Manifest，以及可选的过程诊断和 Provider 原始产物。对外 `result/` 路径不变。

## 对象化执行

`run_core_pipeline()` 统一协调 Native → Evidence → Quality Gate → Fallback Planning → Capability Routing → Provider Policy → Provider Executor → Canonical Builder → Renderer → Audit。

同一次正式解析的计算结果主要通过 Python 对象传递。中间 JSON、Provider 文件和结构化事件保留取证/回放价值，但不是 Core 的 File Bus。新的实现模块、最终化函数及运行目录使用语义名称；旧 Manifest 的 `stage`/`substage` 等契约字段仍保留兼容，不应再用于描述架构分层。

当前正式入口始终传入 `execute_providers=True` 及 Provider 配置、Registry、Normalizer。直接调用 `run_core_pipeline(..., execute_providers=False)` 可能先生成规划产物，但**当前实现会明确抛出异常**，不是受支持的纯规划成功模式。

## Provider 执行

执行器按候选链进行确定性升级波次，同一运行内复用已初始化的 Provider，并在 `finally` 中尝试关闭已创建的实例。生产闭包验证会在 Provider 实际创建前检查配置的启用状态和可解析性。

默认六引擎及候选顺序保持原样。扩展 Provider 必须显式注册其 Adapter/Normalizer；指定 `provider_chain_overrides` 才会改变运行候选链。详见 [插件接入说明](PROVIDER_PLUGINS_ZH.md)。

运行结果会包含 `production_execution_manifest.json` 与 `selected_prediction_index.json` 等可追踪产物；它们用于审查执行过程和选择依据，不取代真实内容准确率评测。

## 成功语义

Provider 的 `SUCCESS`、执行器接受结果和 Audit PASS 均不等于 OCR 内容逐字正确。Audit 核验的是结构、来源与渲染合同；业务准确率需要通过带 Ground Truth 的 PDF Benchmark 单独量化。
