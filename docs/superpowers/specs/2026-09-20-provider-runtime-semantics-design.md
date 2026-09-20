# Provider Runtime Semantics Design

## Scope

Phase 3 在不安装 Provider package、不创建隔离环境、不下载模型的前提下，收紧生产
Provider 配置与 Registry 语义。冻结文件
`configs/frozen/stage9_route_candidates_prod_v001.json` 不得修改。

## Production closure

生产 Registry 只包含六个实例：

```text
rapidocr_ch_light
paddleocr_v5_mobile
paddleocr_vl_16
mineru_local
marker_local
docling_local
```

`pp_structure_v3_light` 仍可保留 adapter/benchmark 历史，但不进入默认生产 Registry。
Tesseract、独立 Surya 和 generic CLI 同样不进入生产 Registry。

## Configuration semantics

每个新生产 Provider 配置必须显式包含：

```text
runtime_enabled: bool
benchmark_enabled: bool
```

`runtime_enabled` 是 Registry resolve 的唯一开关；`benchmark_enabled` 不影响 runtime。
生产 Registry 不兼容性回退到旧 `enabled`。若将来需要读取旧配置，必须通过独立 migration
adapter 显式转换，避免一个字段继续承担两种语义。

## Validation boundary

`validate_runtime_provider_closure(policy, provider_configs)` 在 executor 创建 Provider、进入
wave 或写运行产物之前扫描整份 policy。每个引用必须：

1. 存在于 Registry config；
2. `runtime_enabled is True`；
3. adapter kind 属于生产允许集合。

任何不一致都抛出带 Provider 名称的配置错误。Registry 自身也拒绝 runtime-disabled
Provider，形成启动校验和单实例 resolve 的双层防线。

## Environment and cache boundary

主 `.venv` 承载 Core、RapidOCR 和 Paddle 栈；MinerU、Marker、Docling 使用已有 worker
边界下各自的新 V2 环境。模型继续使用用户级 PaddleX/Hugging Face/MinerU cache，禁止把模型
复制进仓库或引用旧工程 virtualenv。真实验证顺序固定为 import、preflight、cache discovery、
single-task smoke；本轮不执行这些安装后步骤。

## Service boundary

Core package 不依赖 FastAPI、UploadFile、HTTP request/response、Celery。未来 service adapter
仅包装稳定的文件路径型 Core API；依赖方向只能是 service -> Core。

## Testing

- 配置 contract 锁定六个 runtime-enabled Provider 和拆分字段；
- Registry 测试覆盖 benchmark-disabled/runtime-enabled、runtime-disabled 和 PP-Structure 排除；
- closure validator 测试覆盖 missing、disabled 和 unsupported；
- executor 测试证明闭包错误发生在任何 Provider resolve/execute 之前；
- import boundary contract 防止 Core 引入 Web/Celery 框架。

