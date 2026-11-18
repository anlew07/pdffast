# PDFFast 文档索引与资料治理

本索引区分 **当前维护入口**、**专项技术文档** 和 **历史记录**。仓库统一命名为 PDFFast；旧 V2/V3 标识仅说明当时的技术阶段。**历史资料不因改名批量改写或删除。**

## 一、当前维护入口（优先）

| 文档 | 谁应该看 | 状态 |
|---|---|---|
| [项目 README](../README.md) | 所有用户 | 统一项目介绍与入口 |
| [AI / 开发人员快速接手](../AGENTS.md) | 维护者与 AI | 代码路径、变更边界、测试约束 |
| [快速上手](QUICKSTART_ZH.md) | 本地开发者 | 新克隆、基本测试、CLI、Python API |
| [环境重建与安全清理](REBUILD_ZH.md) | 新装机/迁移 | 模型与缓存清单、重建验证、删除前门禁 |
| [维护者手册](MAINTENANCE_ZH.md) | Bug/OCR/质量维护 | 问题定位、修改、回归、PR 验收 |
| [版本管理与命名规范](VERSIONING_ZH.md) | 发布与集成 | Git 分支、标签、JudgeAI 锁 |
| [架构概览](ARCHITECTURE.md) | 理解 Core | 当前对象化 Pipeline |
| [Core 流程](PIPELINE.md) | 阅读执行路径 | 关键组件与运行阶段 |
| [Python 接入](INTEGRATION_ZH.md) | 外部系统 | 公共 API 与异常 |
| [输出模式](OUTPUT_MODES_ZH.md) | 集成与排障 | `result/` 和诊断产物 |
| [故障排查](TROUBLESHOOTING_ZH.md) | 日常问题 | 从日志到责任模块 |

日常只读资源盘点命令：`python scripts/audit_environment.py`；缺项门禁加 `--strict`，重模型哈希检查加 `--hashes`。详见[环境重建](REBUILD_ZH.md)。

## 二、专项技术文档（按需核对源码）

- [Provider 插件接入](PROVIDER_PLUGINS_ZH.md)：Adapter/Normalizer/Registry 合同。
- [Provider Benchmark](PROVIDER_BENCHMARK_ZH.md)：候选路由与有 Ground Truth 的质量评估。
- [Indra 独立运行时](indra_runtime.md)：隔离环境、模型 revision、哈希校验、三模型实验；包含研发时间线，执行前核对当前命令。
- [生产 Provider 审计](PRODUCTION_PROVIDER_AUDIT.md)：阶段性证据，不能代替当前环境探针。
- [MiniCPM-OCR 实验](MINICPM_OCR_BENCHMARK_ZH.md)：可选候选，不代表已进入默认路线。
- [OmniDocBench 官方评估](OMNIDOCBENCH_OFFICIAL_EVAL_ZH.md)与[分层评估](OMNIDOCBENCH_STRATIFIED_ZH.md)：研究材料与许可需单独确认。

## 三、历史资料与兼容记录

以下文件**保留原始叙述和当时路径，不作为新机器安装说明**：

- [早期迁移规划](MIGRATION_PLAN.md)。
- [Provider Runtime 环境历史](PROVIDER_RUNTIME_ENVIRONMENTS.md)、[早期验收记录](PROVIDER_RUNTIME_VALIDATION.md)：部分命令和路径仍指向旧 V2 环境。
- [历史设计、修复与实验报告](reviews/)：具体问题的当时证据与决策。
- [设计方案和开发计划](superpowers/)：当时阶段任务，不等同于现行支持合同。
- [早期独立环境审计](reviews/v3-independent-environment-and-git-baseline.md)：记录 V3 阶段的参考环境依赖限制。

**归档策略**：本轮只建立索引、修订当前入口，不移动/删除旧文档，避免破坏文档引用及溯源。后续如要移动，应独立 PR，包含旧→新映射和全链检查。

## 四、文档维护规则

- 安装/运行命令只以现行仓库、已锁定依赖与源码实际参数为准，优先使用**相对路径**。
- 新的 Provider、模型文件、CLI 参数或用户可见结果改变时，须同时更新相关操作文档与验收范围。
- 历史实测数据注明日期、样本、Profile、机器、Git SHA，不能无条件写成当前基准。
- 环境探针 PASS 只代表资源检查，不等于真实模型推理和 OCR 文字准确。
- `README` 负责导航；内部深入排障与方法写在维护文档，避免把所有历史资料堆在首页。
