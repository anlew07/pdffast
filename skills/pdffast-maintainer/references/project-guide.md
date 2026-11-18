# PDFFast V3 代码地图、接口与改动矩阵
参考创建时 `main`：`164fc49c1a4bc305864639a4a5fc36be2f098489`。每次先根据当前 checkout 的 `project_index.py` 实时扫描，再实际阅读源码；此文档是导航，不是可执行 API 的保证。

## 主调用链
```text
pdffast/parser.py  PDFFastParser.parse(Path, *, run_id, case_id)
 → pdffast/application/parse_service.py  ParseService.parse/_parse
   → pdffast/pipeline/runner.py  run_core_pipeline(PipelineContext, ...)
       → native/{profiler,sections,structure,tables,text_flow}.py
       → quality/evidence.py → quality/gate.py
       → fallback/{planner,router,policy,executor}.py
       → providers/base.py → providers/registry.py → runtime_normalization.py
       → canonical/builder.py + structure_reconciliation/*
       → render/llm_ready.py → audit/structure_boundary.py
 → pdffast/result.py ParseResult
HTTP: pdffast/service/app.py POST /parse → Parser → ParseResponse
CLI: scripts/run_pipeline.py → Parser
```
V3 运行中对象传递；历史 Stage 编号与 JSON 供诊断/回放，不是内部文件总线。

## 改什么，读哪里，测什么
| 要改的功能 | 核心源码 | 首选测试/合同 |
|---|---|---|
| Python API/参数/结果 | `parser.py`, `config.py`, `result.py`, `application/parse_service.py` | `test_parse_service.py`, `test_input_fingerprint.py`, `test_package.py` |
| HTTP 上传/响应/关闭 | `service/app.py`, `runtime.py` | `test_service_shutdown.py`, `test_shutdown_cleanup.py`; HTTP /parse |
| 原生章节/表格/文字流 | `native/{sections,tables,text_flow,profiler}.py` | `test_generic_sections.py`, `test_table_result_handoff.py`, regression |
| 质量门控和路由条件 | `quality/evidence.py`, `quality/gate.py` | `test_evidence_quality_objects.py`, `test_object_routing.py` |
| Provider 路由和失败回退 | `fallback/{router,policy,executor}.py`, `providers/profiles.py` | `test_fallback_executor.py`, `test_provider_profiles.py` |
| 新 OCR 引擎 | `providers/{base,registry,runtime_normalization,normalization}.py`，参考 `minicpm_ocr.py` | `test_provider_plugins.py`, `test_runtime_normalization.py`, `tests/provider/test_provider_contracts.py` |
| 文档结构/Markdown/Audit | `canonical/builder.py`, `render/llm_ready.py`, `audit/structure_boundary.py`, `structure_reconciliation/` | `test_canonical_document_units.py`, `test_document_unit_renderer.py`, `test_document_unit_audit.py` |
| 独立 Provider 评分 | `tools/provider_benchmark/{prepare,run,report,evaluate}.py` | `tests/unit/test_provider_benchmark*.py` |
| 结果 Manifest/产物路径 | `pipeline/artifacts.py`, `result.py`, `application/input_fingerprint.py` | `test_artifact_paths.py`, `test_output_governance.py` |

## 稳定合同
- 公开 `PDFFastParser.parse()` 返回 `ParseResult`：`canonical`、`markdown`、`audit`、`artifacts`，旧键 `result["structure_audit"]` 保留映射。新增参数同时核实 `ParserConfig`、`ParseService`、HTTP 与集成文档。
- `providers/base.py` 的 `Provider` 协议：`preflight() -> ProviderPreflight`、`initialize()`、`execute(ProviderTask) -> RawProviderResult`、`close()`；Normalizer 输出 `CanonicalPrediction`，不可凭空生成 tables/formulas/reading_blocks/relations。
- `providers/profiles.py` 的配置必须完整覆盖四路线：`PAGE_DOCUMENT_OCR`、`PAGE_DOCUMENT_LAYOUT_PARSE`、`REGION_MULTIMODAL_PARSE`、`INLINE_CONTEXT_PARSE`；`enabled_providers` 引用完整，未指定 Profile 时保留冻结路由。
- HTTP `GET /health` 不证明模型可推理，`POST /parse` 上传字段 `file`，响应 `schema_version=1.0` 是接口版本不是产品版本。Core 不允许依赖 FastAPI/Celery。
- `outputs/<run_id>/result` 的 `document.json`、`document.md`、`audit.json`、`manifest.json`；manifest 存在不能证明成功。
- JudgeAI 固定 PDFFast Git commit，变更后还需 JudgeAI 单独升级与回归。

首次读 `README.md`、`docs/ARCHITECTURE.md`、`docs/PIPELINE.md`、`docs/INTEGRATION_ZH.md`、`docs/PROVIDER_PLUGINS_ZH.md` 和 `docs/PROVIDER_BENCHMARK_ZH.md`。
