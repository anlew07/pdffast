# PDFFast 文档索引

## 当前 V3 规范与操作文档

以下文档描述当前 V3：

- [快速上手](QUICKSTART_ZH.md)：安装、Python API、CLI 和输出。
- [架构](ARCHITECTURE.md)：对象化 Pipeline、Provider 边界和服务集成。
- [Pipeline](PIPELINE.md)：正式执行链路、对象传递与成功语义。
- [Provider Runtime 环境](PROVIDER_RUNTIME_ENVIRONMENTS.md)：主环境、隔离 Worker、模型资产和预检。
- [Provider 插件接入](PROVIDER_PLUGINS_ZH.md)：Adapter、Normalizer、Registry 和显式启用。
- [输出模式](OUTPUT_MODES_ZH.md)：minimal / diagnostic / full。
- [生产解析身份合同](contracts/production_parser_identity_v1.md)：V1 身份与指纹合同。
- [Parser Provenance 合同](contracts/parser_provenance_v1.md)：执行来源与统计证明。
- [部署恢复合同](contracts/deployment_control_v1.md)：进程监管与部署健康。

## 历史记录与迁移证据

`MIGRATION_PLAN.md`、`docs/superpowers/plans/*v2*` 及带日期的
`docs/reviews/*` 是当时阶段的设计、实验和审查记录。它们用于解释历史决策，不应直接作为
当前代码修改依据、安装命令或验收结果。

特别是 V2 环境记录中的绝对路径、旧虚拟环境、旧模型缓存和测试数字均已过期。当前操作必须
以仓库源码、配置、lock 文件、当前合同测试和当前 CI 为准。

## 测试分层

- 默认测试：`uv run pytest -q`，只运行当前 V3 单元/合同测试和确定性离线测试。
- 可选 Provider Runtime：`uv run pytest -q -m provider`，需安装相应隔离 Runtime。
- [真实数据回归说明](../tests/regression/README.md)：真实 PDF 与既有回归产物的准备方式。
- [历史迁移测试说明](../tests/migration/README.md)：只读旧 V2 checkout 的可选对照，不属于当前运行依赖。
