# PDFFast V3 架构

PDFFast V3 是一个面向 PDF 解析的对象化 Pipeline。对外使用 `PDFFastParser.parse(pdf_path)`，返回包含 Markdown、Canonical JSON、Audit 和产物路径的 `ParseResult`。

Core 不依赖 HTTP、FastAPI、Celery 等传输层对象；当前项目已有可选的 FastAPI 服务适配器，JudgeAI 也可以通过嵌入式调用接入。

## 核心运行链路

```text
PDF
  → Native：原生文本、章节、表格和阅读流
  → Evidence：来源与覆盖证据
  → Quality Gate：决定是否需要增强
  → Fallback Planning：准备待增强任务
  → Capability Routing：按任务需求选能力类别
  → Provider Policy：选择候选链与回退规则
  → Provider Executor：通过 Registry 调用 Provider
  → Runtime Normalizer：生成 CanonicalPrediction
  → Canonical Builder：生成规范文档
  → Markdown Renderer：输出 LLM-ready 文本
  → Audit：检查结构、来源与渲染合同
  → ParseResult
```

正式 Runtime 以 Python 对象作为主要的数据交接方式；运行中仍会落盘配置、模型输出和诊断 Artifact，以供追踪、回放和兼容既有工具，**但不把本次运行的中间 JSON 文件当作内部数据总线**。

新运行的目录、内部实现文件和最终输出边界采用组件职责命名。历史编号仅作为部分冻结输入、规范 JSON 字段和兼容诊断中的旧标识保留，不代表核心架构尚未完成重构。新增能力应按上述组件职责接入。

## Provider 扩展边界

每个 Provider 通过 `preflight / initialize / execute / close` 契约被 Registry 创建；执行器负责候选升级、异常记录、任务结果选择与清理。各 Adapter 返回 `RawProviderResult`，由独立 Normalizer 标准化为 `CanonicalPrediction`，后续交给现有 Canonical/Renderer/Audit 处理。

默认生产 Provider 集合和路由策略保持受控；新增插件必须从可信配置中显式注册，且只有配置候选链后才会参与生产路由。详见 [Provider 插件接入说明](PROVIDER_PLUGINS_ZH.md)。

MinerU、Marker、Docling 在独立 Python Worker 环境中运行；对应模型缓存不随源码仓库提供。插件接入成功不代表已经通过真实 PDF 的内容质量或资源验收。

## 集成与部署

直接 Python 调用和 FastAPI 服务是对同一个 Core 的不同调用方式。JudgeAI 的嵌入式集成使用锁定的 PDFFast Git 版本，更新本仓库不会自动升级 JudgeAI。对外响应合同与内部诊断 Schema 应独立管理。
