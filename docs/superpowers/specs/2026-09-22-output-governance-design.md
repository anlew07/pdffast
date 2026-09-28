# PDFFast 输出治理与产物分层设计

## 目标

在不改变解析算法、Provider escalation 顺序、Frozen route 或最终 Canonical 内容的前提下，
把 PDFFast 从开发阶段的 Stage 输出形态收口为可被其他 Python 系统调用的工具项目。
调用方默认只接触稳定的 `result/` 目录和 `PDFFastParser.parse()` 返回值；旧 Stage 产物继续
作为内部诊断和回归数据保留。

## 运行模式

公共 API 支持三种产物模式：

- `minimal`：默认模式。流水线仍生成内部所需文件，但调用方只使用 `result/`；内部目录保留在
  当前 run 目录，不主动删除。
- `diagnostic`：在 `result/` 之外，明确保留日志和关键中间产物，便于定位 Provider、质量门和
  结构分析问题。
- `full`：保留现有完整 Stage 目录和所有调试产物，供迁移回归和深度排查使用。

模式只控制产物可见性和日志策略，不改变任何阶段的输入、输出内容或执行顺序。

## 目录契约

每次运行的目录保持独立：

```text
<output_root>/<run_id>/
  result/
    document.json
    document.md
    audit.json
    manifest.json
  diagnostics/
    logs/pipeline.log
    internal/                 # Stage 1-N 兼容产物的用户不可见分组
  01_stage1/ ... 10_2_1/      # full 模式保留；兼容层可继续写入
```

第一版不删除内部文件，避免影响现有回归、失败排查和旧工具链。对外 API 和文档只承诺
`result/`、日志路径和运行元数据，不要求调用方理解 Stage 编号。

## 输出边界

Core API 默认静默。Stage 内部已有的 `print_summary()` 和 Provider 的 stdout/stderr 在
编排边界被捕获并写入 `diagnostics/logs/pipeline.log`。Core 不引入 FastAPI、Celery 或 HTTP
类型。CLI 可以在自己的边界显示简洁进度，但不直接暴露 Stage 调试摘要。

失败时抛出稳定的 PDFFast 异常，异常携带 run 目录和日志路径；原始 traceback 保存在日志中。

## 公共接口

`PDFFastParser.parse(pdf_path)` 继续是主入口。Parser 配置新增产物模式和日志开关；返回结果
保持向后兼容的 mapping 行为，同时提供稳定的结果目录字段。内部 `run_core_pipeline`、
`run_stage10` 和 `ArtifactPaths` 继续存在，但标记为内部实现。

## 兼容与不变项

- `configs/frozen/stage9_route_candidates_prod_v001.json` byte-for-byte 不变。
- 不调整算法阈值、Provider chain、模型缓存和环境边界。
- Canonical JSON、Markdown、Structure Audit 的语义和内容不变；新增目录只是稳定副本/索引。
- 现有 Stage 路径继续可用于 reference-bound 测试和完整诊断。

## 验证

新增测试覆盖静默输出、日志捕获、三种模式的目录契约、稳定异常和最终结果一致性；随后运行
现有 unit、contract、provider fake、default 与 reference-bound 回归测试。
