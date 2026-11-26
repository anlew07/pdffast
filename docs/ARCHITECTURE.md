# PDFFast V3 架构

PDFFast V3 使用对象化 Pipeline 解析 PDF。普通入口为 `PDFFastParser.parse(pdf_path)`，锁定生产的版本化入口为 `PDFFastParser.parse_request(pdf_path, request)`，两者都返回 `ParseResult`。

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

代码和产物里仍保留少量 `Stage 8`、`Stage 9`、`Stage 10` 等历史编号，这是旧实现迁移后的内部命名与兼容标识，不代表核心架构尚未完成重构。新增能力应按上述组件职责接入，而不是围绕编号重新设计一套阶段流水线。

## Provider 扩展边界

每个 Provider 通过 `preflight / initialize / execute / close` 契约被 Registry 创建；执行器负责候选升级、异常记录、任务结果选择与清理。各 Adapter 返回 `RawProviderResult`，由独立 Normalizer 标准化为 `CanonicalPrediction`，后续交给现有 Canonical/Renderer/Audit 处理。

默认生产 Provider 集合和路由策略保持受控；新增插件必须从可信配置中显式注册，且只有配置候选链后才会参与生产路由。详见 [Provider 插件接入说明](PROVIDER_PLUGINS_ZH.md)。

Indra、MinerU、Marker、Docling 在独立 Python Worker 环境中运行；对应模型缓存不随源码仓库提供。插件接入成功不代表已经通过真实 PDF 的内容质量或资源验收。

## 集成与部署

普通 Python、Embedded V1 与可选 HTTP 服务使用同一个 Core。Embedded 在进入 Core 前核验输入摘要和部署 Profile，解析完成后交付可验证结果及 Provider 证据。JudgeAI 固定 PDFFast Git 提交，按 [接入合同](integration/JUDGEAI_EMBEDDED_EXECUTION_CONTRACT_V1.md)验证回执。HTTP 服务使用自身的响应结构。
